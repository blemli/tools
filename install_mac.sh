echo "Installing blemli tools in $(pwd)"
read -p "Are you sure? " -n 1 -r
echo    # (optional) move to a new line
if echo "$REPLY" | grep -Eq "^[Yy]$"
then
	git clone blemli/tools
	cd tools
	chmod +x install.sh && ./install.sh
fi
