#!/bin/bash
set -e

if ! command -v synapse >/dev/null 2>&1; then
    echo "Synapse CLI not found."
    echo "Install first: npm install -g synapse-oss"
    exit 1
fi

synapse install
synapse onboard
