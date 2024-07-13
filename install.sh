if [ ! -d ".venv" ]; then
    uv venv
fi
source .venv/bin/activate
INTERPRETER_PATH=$(which python3)

#loop trough all tooldirectories (except _shims) and make the <Tool>.py executable and install the requirements
for TOOL in $(ls -d */ | grep -v _shims);
do
    TOOL=${TOOL%?}
    chmod +x $TOOL/$TOOL.py
    #install the requirements for the tool if they exist
    [ -f $TOOL/requirements.txt ] && uv pip install -r $TOOL/requirements.txt
    # add a shim for the tool in the "shims" directory
    echo "#!/bin/bash" > _shims/$TOOL
    chmod +x _shims/$TOOL
    echo "$INTERPRETER_PATH $(pwd)/$TOOL/$TOOL.py \$@" >> _shims/$TOOL
    #todo add tab completion:
    echo "eval \"\$($TOOL=source_zsh $TOOL)\"" >> ~/.zshrc
done
echo export PATH="\"\$PATH:$(pwd)/_shims\"" >> ~/.zshrc