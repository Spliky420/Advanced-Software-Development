"""
Extended Agentic Loop Mixin for Maxwell's Glossary Feature
Adds MCP and RAG validation modes to the standard Plan-Act-Observe-Adapt loop
"""

import json
import requests
from pathlib import Path
from typing import Dict, Any, Optional, Tuple


class MaxwellGlossaryAgenticLoop:
    """
    Extends the standard agentic loop with MCP and RAG validation modes:
    PLAN -> ACT -> OBSERVE -> VALIDATE_MCP -> VALIDATE_RAG -> ADAPT
    """

    def __init__(self,
                 mcp_server_url: str = "http://localhost:8090",
                 rag_server_url: str = "http://localhost:8091",
                 enable_mcp_validation: bool = True,
                 enable_rag_validation: bool = True,
                 strict_mode: bool = False,
                 confidence_threshold: float = 0.3):
        """
        Initialize the extended agentic loop

        Args:
            mcp_server_url: URL of the shared local MCP server
            rag_server_url: URL of the shared local RAG server
            enable_mcp_validation: Whether to run MCP validation
            enable_rag_validation: Whether to run RAG validation
            strict_mode: If True, both validations must pass; if False, either can pass
            confidence_threshold: Minimum confidence for validation to pass
        """
        self.mcp_server_url = mcp_server_url
        self.rag_server_url = rag_server_url
        self.enable_mcp_validation = enable_mcp_validation
        self.enable_rag_validation = enable_rag_validation
        self.strict_mode = strict_mode
        self.confidence_threshold = confidence_threshold

        # Validation results storage
        self.validation_results = {
            "mcp": {"passed": False, "confidence": 0.0, "details": {}},
            "rag": {"passed": False, "confidence": 0.0, "details": {}}
        }

    def _make_mcp_request(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Make a request to the MCP server"""
        try:
            response = requests.post(
                f"{self.mcp_server_url}{endpoint}",
                json=data,
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"MCP server error: {response.status_code}", "details": response.text}
        except Exception as e:
            return {"error": f"Failed to connect to MCP server: {str(e)}"}

    def _make_rag_request(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Make a request to the RAG server"""
        try:
            response = requests.post(
                f"{self.rag_server_url}{endpoint}",
                json=data,
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"RAG server error: {response.status_code}", "details": response.text}
        except Exception as e:
            return {"error": f"Failed to connect to RAG server: {str(e)}"}

    def validate_mcp_context(self, term: str, initial_definition: str = "") -> Dict[str, Any]:
        """
        VALIDATE_MCP: Check term against MCP financial context

        Args:
            term: The financial term to validate
            initial_definition: Any initial definition (from database or Ollama)

        Returns:
            Validation result with passed/failed status and confidence
        """
        if not self.enable_mcp_validation:
            return {"passed": True, "confidence": 1.0, "details": {"skipped": True}}

        # Validate term financial relevance
        validation_data = {"term": term}
        mcp_response = self._make_mcp_request("/validate/term", validation_data)

        if "error" in mcp_response:
            mcp_result = {"passed": False, "confidence": 0.0, "details": mcp_response}
        else:
            # Extract confidence and determine if validation passed
            confidence = mcp_response.get("confidence", 0.0)
            passed = confidence >= self.confidence_threshold and mcp_response.get("valid", False)
            mcp_result = {
                "passed": passed,
                "confidence": confidence,
                "details": {
                    "validation": mcp_response,
                    "term": term
                }
            }

        self.validation_results["mcp"] = mcp_result
        return mcp_result

    def validate_rag_context(self, term: str, definition: str = "") -> Dict[str, Any]:
        """
        VALIDATE_RAG: Check definition against retrieved financial context

        Args:
            term: The financial term
            definition: The definition to validate (from Ollama or database)

        Returns:
            Validation result with passed/failed status and confidence
        """
        if not self.enable_rag_validation:
            return {"passed": True, "confidence": 1.0, "details": {"skipped": True}}

        # Use RAG to retrieve context for the term
        retrieve_data = {
            "query": f"definition explanation meaning of {term} financial term",
            "top_k": 5
        }
        rag_response = self._make_rag_request("/retrieve", retrieve_data)

        if "error" in rag_response:
            rag_result = {"passed": False, "confidence": 0.0, "details": rag_response}
        else:
            # Assess how well the definition aligns with retrieved context
            results = rag_response.get("results", [])
            context_confidence = rag_response.get("confidence", 0.0)

            # Simple heuristic: if we got good results and context confidence is high, validation passes
            # In a more sophisticated implementation, we'd compare the definition with retrieved texts
            passed = len(results) > 0 and context_confidence >= self.confidence_threshold
            rag_result = {
                "passed": passed,
                "confidence": context_confidence,
                "details": {
                    "retrieved_results": results,
                    "query_used": retrieve_data["query"],
                    "definition_provided": definition[:100] + "..." if len(definition) > 100 else definition
                }
            }

        self.validation_results["rag"] = rag_result
        return rag_result

    def run_extended_loop(self,
                         term: str,
                         initial_definition: str = "",
                         generate_definition_func=None) -> Dict[str, Any]:
        """
        Run the extended Plan-Act-Observe-Validate_MCP-Validate_Rag-Adapt loop

        Args:
            term: The financial term to define
            initial_definition: Definition from database (if any)
            generate_definition_func: Function to call Ollama for definition generation

        Returns:
            Complete loop result with all phases and validation outcomes
        """
        loop_result = {
            "term": term,
            "initial_definition": initial_definition,
            "phases": {}
        }

        # =====================================
        # PLAN
        # =====================================
        loop_result["phases"]["plan"] = {
            "phase": "plan",
            "description": f"Plan to define financial term '{term}' using MCP and RAG validation",
            "term": term,
            "has_initial_definition": bool(initial_definition and initial_definition.strip())
        }

        # =====================================
        # ACT
        # =====================================
        # If we have an initial definition from database, use it; otherwise generate
        if initial_definition and initial_definition.strip() and initial_definition != "Error generating definition.":
            final_definition = initial_definition
            llm_called = False
            loop_result["phases"]["act"] = {
                "phase": "act",
                "description": "Retrieved existing definition from database",
                "source": "database",
                "definition": final_definition
            }
        else:
            # Generate definition using Ollama (ACT phase)
            if generate_definition_func:
                try:
                    final_definition = generate_definition_func(term)
                    llm_called = True
                    loop_result["phases"]["act"] = {
                        "phase": "act",
                        "description": "Generated definition using Ollama LLM",
                        "source": "ollama",
                        "definition": final_definition,
                        "llm_called": True
                    }
                except Exception as e:
                    final_definition = "Error generating definition."
                    llm_called = False
                    loop_result["phases"]["act"] = {
                        "phase": "act",
                        "description": f"Failed to generate definition: {str(e)}",
                        "source": "ollama",
                        "definition": final_definition,
                        "llm_called": False,
                        "error": str(e)
                    }
            else:
                final_definition = "No generation function provided"
                llm_called = False
                loop_result["phases"]["act"] = {
                    "phase": "act",
                    "description": "No LLM generation function available",
                    "source": "none",
                    "definition": final_definition,
                    "llm_called": False
                }

        # =====================================
        # OBSERVE
        # =====================================
        loop_result["phases"]["observe"] = {
            "phase": "observe",
            "description": f"Observed definition for term '{term}'",
            "term": term,
            "definition_preview": final_definition[:100] + "..." if len(final_definition) > 100 else final_definition,
            "definition_length": len(final_definition)
        }

        # =====================================
        # VALIDATE_MCP
        # =====================================
        loop_result["phases"]["validate_mcp"] = self.validate_mcp_context(term, final_definition)

        # =====================================
        # VALIDATE_RAG
        # =====================================
        loop_result["phases"]["validate_rag"] = self.validate_rag_context(term, final_definition)

        # =====================================
        # ADAPT
        # =====================================
        # Determine if we should use the definition based on validation results
        mcp_passed = self.validation_results["mcp"]["passed"]
        rag_passed = self.validation_results["rag"]["passed"]

        if self.strict_mode:
            # Both validations must pass
            should_use_definition = mcp_passed and rag_passed
        else:
            # Either validation can pass (or both)
            should_use_definition = mcp_passed or rag_passed

        # If validation fails but we have a definition, we might still use it with lower confidence
        # or fall back to a safer approach
        if not should_use_definition and final_definition not in [
            "Error generating definition.",
            "Definition not available.",
            "No generation function provided"
        ]:
            # We have a definition but validations failed - provide it with warnings
            adapted_definition = final_definition
            adaptation_note = "Definition provided but failed validation(s)"
        elif should_use_definition:
            adapted_definition = final_definition
            adaptation_note = "Definition passed validation(s)"
        else:
            # Fall back to a safe response
            adapted_definition = "Definition unavailable due to validation failure"
            adaptation_note = "All validations failed - using safe fallback"

        loop_result["phases"]["adapt"] = {
            "phase": "adapt",
            "description": f"Adapted definition based on MCP/RAG validation results",
            "mcp_validation_passed": mcp_passed,
            "rag_validation_passed": rag_passed,
            "strict_mode": self.strict_mode,
            "should_use_definition": should_use_definition,
            "adaptation_note": adaptation_note,
            "final_definition": adapted_definition,
            "confidence_score": self._calculate_overall_confidence()
        }

        # Add validation results to final output
        loop_result["validation_results"] = self.validation_results.copy()

        return loop_result

    def _calculate_overall_confidence(self) -> float:
        """Calculate overall confidence based on validation results"""
        mcp_conf = self.validation_results["mcp"]["confidence"]
        rag_conf = self.validation_results["rag"]["confidence"]

        if self.strict_mode:
            # In strict mode, confidence is limited by the weaker validation
            return min(mcp_conf, rag_conf)
        else:
            # In non-strict mode, we can take the maximum or average
            return max(mcp_conf, rag_conf)

    def get_validation_summary(self) -> Dict[str, Any]:
        """Get a summary of validation results for reporting"""
        return {
            "mcp_validation": {
                "passed": self.validation_results["mcp"]["passed"],
                "confidence": self.validation_results["mcp"]["confidence"],
                "details": self.validation_results["mcp"]["details"]
            },
            "rag_validation": {
                "passed": self.validation_results["rag"]["passed"],
                "confidence": self.validation_results["rag"]["confidence"],
                "details": self.validation_results["rag"]["details"]
            },
            "overall_confidence": self._calculate_overall_confidence(),
            "strict_mode": self.strict_mode,
            "validation_enabled": {
                "mcp": self.enable_mcp_validation,
                "rag": self.enable_rag_validation
            }
        }


# Convenience function for easy integration
def create_maxwell_glossary_loop(mcp_url="http://localhost:8090",
                                rag_url="http://localhost:8091",
                                **kwargs) -> MaxwellGlossaryAgenticLoop:
    """Factory function to create a Maxwell glossary agentic loop"""
    return MaxwellGlossaryAgenticLoop(
        mcp_server_url=mcp_url,
        rag_server_url=rag_url,
        **kwargs
    )