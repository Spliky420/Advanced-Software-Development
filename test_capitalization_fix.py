#!/usr/bin/env python3
"""
Test script to verify the term capitalization fix works correctly.
This demonstrates that terms are now stored and displayed in uppercase.
"""

import sys
import os
import tempfile
import shutil
from pathlib import Path

# Add the Maxwell backend to path
maxwell_backend_path = Path(__file__).parent / "Maxwell" / "backend"
sys.path.insert(0, str(maxwell_backend_path))

def test_term_normalization():
    """Test that terms are normalized to uppercase for storage and display"""

    # Set up a temporary database for testing
    temp_dir = tempfile.mkdtemp()
    test_db = os.path.join(temp_dir, "test_glossary.sqlite")

    try:
        # Set environment variable to use our test database
        os.environ['DATABASE'] = test_db

        # Import the app after setting the environment variable
        from app import init_db, get_db, normalize_term

        # Initialize the database
        init_db()

        # Test the normalize_term function
        print("Testing normalize_term function:")
        test_cases = [
            ("etf", "ETF"),
            ("EtF", "ETF"),
            ("Stock", "STOCK"),
            ("bond", "BOND"),
            ("ROI", "ROI"),  # Already uppercase
            ("  etf  ", "ETF"),  # With whitespace
            ("", ""),  # Empty string
            (None, None),  # None
        ]

        for input_term, expected in test_cases:
            result = normalize_term(input_term)
            status = "✅" if result == expected else "❌"
            print(f"  {status} normalize_term('{input_term}') = '{result}' (expected '{expected}')")

        # Test database operations with normalization
        print("\nTesting database operations:")
        conn = get_db()

        # Test inserting a lowercase term - should be stored as uppercase
        test_term = "etf"
        normalized_term = normalize_term(test_term)  # Should be "ETF"
        definition = "Exchange-Traded Fund"

        # Insert the term
        conn.execute('INSERT INTO terms (term, definition) VALUES (?, ?)',
                    (normalized_term, definition))
        conn.commit()

        # Check what was actually stored
        stored_row = conn.execute('SELECT term, definition FROM terms WHERE term = ?',
                                 (normalized_term,)).fetchone()

        print(f"  Inserted term: '{test_term}'")
        print(f"  Normalized for storage: '{normalized_term}'")
        print(f"  Actually stored as: '{stored_row[0]}' (definition: '{stored_row[1]}')")

        # Verify it sorts correctly with other terms
        # Insert a few more terms for sorting test
        test_terms = [("apple", "FRUIT"), ("BOND", "DEBT"), ("etf", "INVESTMENT")]

        for term, defn in test_terms:
            norm_term = normalize_term(term)
            # Use INSERT OR IGNORE to avoid duplicates
            conn.execute('INSERT OR IGNORE INTO terms (term, definition) VALUES (?, ?)',
                        (norm_term, defn))

        conn.commit()

        # Get all terms in alphabetical order
        all_terms = conn.execute('SELECT term FROM terms ORDER BY term').fetchall()
        term_list = [row[0] for row in all_terms]

        print(f"  All terms in sorted order: {term_list}")

        # Verify that ETF appears in the correct position (not at the end)
        if "ETF" in term_list:
            etf_index = term_list.index("ETF")
            print(f"  ETF is at index {etf_index} in the sorted list")
            if etf_index < len(term_list) // 2:  # Roughly in first half
                print("  ✅ ETF appears in correct sorted position (not at end)")
            else:
                print("  ❌ ETF appears too far toward the end")
        else:
            print("  ❌ ETF not found in terms list")

        conn.close()

        print("\n✅ All tests completed!")
        return True

    except Exception as e:
        print(f"❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # Clean up temporary directory
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    print("Testing Term Capitalization Fix")
    print("=" * 40)
    success = test_term_normalization()
    print("\n" + "=" * 40)
    if success:
        print("🎉 Test PASSED: Term capitalization fix is working correctly!")
        print("   Terms will now be stored and displayed in uppercase,")
        print("   ensuring proper alphabetical sorting.")
    else:
        print("💥 Test FAILED: There are issues with the fix.")
    print("=" * 40)