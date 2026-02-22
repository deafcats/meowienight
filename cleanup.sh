#!/bin/bash
# Cleanup script for movie_rec project

echo "🧹 Cleaning up project files..."

# Remove Python cache
echo "Removing __pycache__ directories..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# Remove compiled Python files
echo "Removing .pyc, .pyo files..."
find . -name "*.pyc" -delete 2>/dev/null || true
find . -name "*.pyo" -delete 2>/dev/null || true

# Remove OS files
echo "Removing .DS_Store files..."
find . -name ".DS_Store" -delete 2>/dev/null || true

# Remove empty directories (except important ones)
echo "Removing empty directories..."
find . -type d -empty -not -path "./.git/*" -not -path "./static/uploads/*" -not -path "./data/*" -delete 2>/dev/null || true

echo "✅ Cleanup complete!"

