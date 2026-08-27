#!/usr/bin/env bash
# Seed Maxwell's financial glossary via the API:
#   1. GET /api/glossary/<term>  (creates term via Ollama if missing)
#   2. PUT /api/glossary/<term>  (overwrites with our custom definition)
# Usage: ./seed_glossary.sh
# Ensure the Maxwell backend is running (http://localhost:8021)

API_BASE="http://localhost:8021/api/glossary"

# Helper: URL-encode a string for use in a path segment (spaces -> %20, slash -> %2F)
urlencode() {
    local input="$1"
    # Replace spaces with %20, slash with %2F
    printf '%s' "$input" | sed 's/ /%20/g; s/\//%2F/g'
}

# Define terms and their custom definitions (plain ASCII)
declare -A terms=(
    ["ETF"]="Exchange-Traded Fund - a basket of securities that trades on an exchange."
    ["ROI"]="Return on Investment - a measure of the profitability of an investment."
    ["IPO"]="Initial Public Offering - the first sale of stock by a private company to the public."
    ["P/E Ratio"]="Price-to-Earnings Ratio - a valuation ratio of a company's current share price compared to its per-share earnings."
    ["Market Cap"]="Market Capitalization - the total market value of a company's outstanding shares of stock."
    ["Dividend"]="A distribution of a portion of a company's earnings to its shareholders."
    ["Bull Market"]="A market condition where prices are rising or are expected to rise."
    ["Bear Market"]="A market condition where prices are falling or are expected to fall."
    ["Liquidity"]="The ease with which an asset can be converted into cash without affecting its market price."
    ["Volatility"]="A statistical measure of the dispersion of returns for a given security or market index."
)

echo "Seeding glossary terms via $API_BASE (GET then PUT) ..."

for term in "${!terms[@]}"; do
    definition="${terms[$term]}"
    encoded_term=$(urlencode "$term")
    echo "Processing term: $term (encoded: $encoded_term)"

    # Step 1: GET to ensure term exists (triggers Ollama generation if needed)
    echo "  → GET to create placeholder..."
    get_resp=$(curl -s -w "\nHTTP_STATUS:%{http_code}" "$API_BASE/$encoded_term")
    get_body=$(echo "$get_resp" | sed -e 's/HTTP_STATUS\:.*//')
    get_status=$(echo "$get_resp" | tr -d '\n' | sed -e 's/.*HTTP_STATUS://')
    if [[ "$get_status" -ge 200 && "$get_status" -lt 300 ]]; then
        echo "    ✅ GET succeeded (HTTP $get_status)"
    else
        echo "    ❌ GET failed (HTTP $get_status): $get_body"
        continue
    fi

    # Step 2: PUT to set our custom definition
    echo "  → PUT custom definition..."
    put_resp=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X PUT "$API_BASE/$encoded_term" \
        -H "Content-Type: application/json" \
        -d "{\"definition\":\"$definition\"}")
    put_body=$(echo "$put_resp" | sed -e 's/HTTP_STATUS\:.*//')
    put_status=$(echo "$put_resp" | tr -d '\n' | sed -e 's/.*HTTP_STATUS://')
    if [[ "$put_status" -ge 200 && "$put_status" -lt 300 ]]; then
        echo "    ✅ PUT succeeded (HTTP $put_status)"
    else
        echo "    ❌ PUT failed (HTTP $put_status): $put_body"
    fi
done

echo "Seeding complete."