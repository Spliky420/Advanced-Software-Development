#!/usr/bin/env python3
"""
Verification script for shared local services integration
This demonstrates how the components work together
"""

import sys
import os
from pathlib import path

# Add current directory to path
sys.path.append(str(Path(__file__).parent))

def test_imports():
    """Test that all modules can be imported"""
    print("Testing imports...")

    try:
        from agentic_loop_mixin import create_maxwell_glossary_loop, MaxwellGlossaryAgenticLoop
        print("✅ Agentic loop mixin imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import agentic loop mixin: {e}")
        return False

    try:
        # Test that we can create an instance
        loop = create_maxwell_glossary_loop()
        print("✅ Agentic loop instance created successfully")
    except Exception as e:
        print(f"❌ Failed to create agentic loop instance: {e}")
        return False

    return True

def test_knowledge_base_loading():
    """Test that knowledge base files can be loaded"""
    print("\nTesting knowledge base loading...")

    try:
        import json
        kb_path = Path(__file__).parent / "financial_knowledge_base"

        # Test terms.json
        with open(kb_path / "terms.json", 'r') as f:
            terms_data = json.load(f)
        print(f"✅ Loaded {len(terms_data.get('financial_terms', []))} financial terms")

        # Test relationships.json
        with open(kb_path / "relationships.json", 'r') as f:
            rel_data = json.load(f)
        print("✅ Relationships data loaded successfully")

        # Test rules.json
        with open(kb_path / "rules.json", 'r') as f:
            rules_data = json.load(f)
        print("✅ Rules data loaded successfully")

        return True
    except Exception as e:
        print(f"❌ Failed to load knowledge base: {e}")
        return False

def test_mock_validation():
    """Test the mock validation functionality"""
    print("\nTesting mock validation...")

    try:
        from agentic_loop_mixin import MaxwellGlossaryAgenticLoop

        # Create loop with validation disabled to test mocks
        loop = MaxwellGlossaryAgenticLoop(
            enable_mcp_validation=False,
            enable_rag_validation=False
        )

        # Mock the validation methods to return known results
        def mock_mcp_validation(term, definition=""):
            return {"passed": True, "confidence": 0.9, "details": {"mock": True}}

        def mock_rag_validation(term, definition=""):
            return {"passed": True, "confidence": 0.85, "details": {"mock": True}}

        # Replace validation methods
        loop.validate_mcp_context = mock_mcp_validation
        loop.validate_rag_context = mock_rag_validation

        # Test the extended loop
        result = loop.run_extended_loop(
            term="ETF",
            initial_definition="",
            generate_definition_func=lambda x: f"Mock definition for {x}"
        )

        # Check structure
        assert "term" in result
        assert result["term"] == "ETF"
        assert "phases" in result
        assert "validation_results" in result

        print("✅ Extended agentic loop executed successfully")
        print(f"   - Final definition: {result.get('phases', {}).get('adapt', {}).get('final_definition', 'N/A')}")
        print(f"   - MCP validation passed: {result.get('validation_results', {}).get('mcp', {}).get('passed', False)}")
        print(f"   - RAG validation passed: {result.get('validation_results', {}).get('rag', {}).get('passed', False)}")

        return True
    except Exception as e:
        print(f"❌ Mock validation test failed: {e}")
        return False

def main():
    """Run all verification tests"""
    print("=" * 60)
    print("Shared Local Services Integration Verification")
    print("=" * 60)

    tests = [
        test_imports,
        test_knowledge_base_loading,
        test_mock_validation
    ]

    passed = 0
    total = len(tests)

    for test in tests:
        if test():
            passed += 1
        print()  # Blank line between tests

    print("=" * 60)
    print(f"Verification Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All verification tests passed!")
        print("\nThe shared local services implementation is ready.")
        print("To use in development:")
        print("  1. Start MCP server:  python shared-local-services/mcp_server.py")
        print("  2. Start RAG server:  python shared-local-services/rag_server.py")
        print("  3. Run Maxwell backend normally (will auto-discover services)")
        print("  4. In CI/test environments, mocks will be used automatically")
        return 0
    else:
        print("❌ Some verification tests failed.")
        return 1

if __name__ == "__main__":
    sys.exit(main())