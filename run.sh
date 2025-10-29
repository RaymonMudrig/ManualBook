#!/bin/bash
#
# ManualBook Pipeline Runner with Environment Loading
#
# Usage:
#   ./run.sh                    # Run full pipeline
#   ./run.sh --start-server     # Run pipeline and start server
#   ./run.sh --skip-docx        # Skip DOCX conversion
#

# Load environment variables from .env file
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
    echo "✓ Loaded environment from .env"
fi

# Show current provider
echo "Using API Provider: ${API_PROVIDER:-openai}"
echo ""

# Run the Python pipeline with all arguments passed through
python run_pipeline.py "$@"
