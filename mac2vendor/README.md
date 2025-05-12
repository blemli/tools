# mac2vendor

A command-line tool to look up vendor information from MAC addresses.

## Installation

### Using pipx (recommended)

[pipx](https://pypa.github.io/pipx/) is a tool to install and run Python applications in isolated environments.

```bash
# Install pipx if you don't have it already
pip install --user pipx
pipx ensurepath

# Install mac2vendor
pipx install .
```

### Using pip

```bash
pip install .
```

## Usage

```bash
# Look up a MAC address
mac2vendor 00:11:22:33:44:55

# Show information about the manuf file
mac2vendor --info

# Force update of the manuf file
mac2vendor --update 00:11:22:33:44:55

# Disable automatic updates
mac2vendor --no-update 00:11:22:33:44:55

# Output only the vendor name (no progress bars or other messages)
mac2vendor --quiet 00:11:22:33:44:55
```

## Shell Completion

mac2vendor supports shell completion for MAC addresses and options. To enable shell completion:

### Bash

Add the following to your `~/.bashrc`:

```bash
eval "$(register-python-argcomplete mac2vendor)"
```

### Zsh

Add the following to your `~/.zshrc`:

```zsh
autoload -U bashcompinit
bashcompinit
eval "$(register-python-argcomplete mac2vendor)"
```

### Fish

Add the following to your `~/.config/fish/config.fish`:

```fish
register-python-argcomplete --shell fish mac2vendor | source
```

## Development

### Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/mac2vendor.git
cd mac2vendor

# Install in development mode
pip install -e .
```

### Running Tests

```bash
# Run tests
pytest
