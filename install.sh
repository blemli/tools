#!/bin/bash

# Create virtual environment if not exists
if [ ! -d ".venv" ]; then
    uv venv
fi

# Activate the virtual environment
source .venv/bin/activate
INTERPRETER_PATH=$(which python3)

# Loop through all tool directories (except _shims)
for TOOL in $(ls -d */ | grep -v _shims); do
    # Remove trailing slash from directory name
    TOOL=${TOOL%/}
    
    # Make the tool's main Python file executable
    chmod +x "$TOOL/$TOOL.py"
    
    # Install requirements if they exist
    if [ -f "$TOOL/requirements.txt" ]; then
        uv pip install -r "$TOOL/requirements.txt"
    fi
    
    # Add a shim for the tool in the _shims directory
    echo "#!/bin/bash" > _shims/$TOOL
    chmod +x _shims/$TOOL
    echo "$INTERPRETER_PATH $(pwd)/$TOOL/$TOOL.py \$@" >> _shims/$TOOL
    
    # TODO: Add tab completion support:
    # echo "eval \"\$($TOOL=source_zsh $TOOL)\"" >> ~/.zshrc
done

# Add _shims to system PATH using /etc/paths.d (macOS standard method)
SHIMS_PATH="$(pwd)/_shims"
PATHS_FILE="_shims"

echo "Adding _shims directory to system PATH using /etc/paths.d..."
echo "$SHIMS_PATH" | sudo tee /etc/paths.d/$PATHS_FILE > /dev/null
echo "Path added to /etc/paths.d/$PATHS_FILE"

# Remove shims for tools that no longer exist
for SHIM in _shims/*; do
    TOOL_NAME=$(basename "$SHIM")
    if [ ! -d "$TOOL_NAME" ]; then
        echo "Removing shim for non-existent tool: $TOOL_NAME"
        rm "$SHIM"
    fi
done

# Inform the user that they need to restart their terminal or source their profile
echo "PATH update complete. Please restart your terminal or run 'source /etc/profile' to apply changes."
