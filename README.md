# tools

**the right tool for the job**

## get started

### macOS & linux

``````bash
git clone blemli/tools
cd tools
chmod +x install.sh && ./install.sh
``````

or if you are lazy:

```bash
curl -L blem.li/tools_mac | sh
```

### Windows

```powershell
git clone blemli/tools
cd tools
./install.ps1
```

or if you are lazy:

``````powershell
irm blem.li/tools_win | iex
``````



> [!IMPORTANT]
>
> Get Help with `mytool --help`



## tools

|                  |                                                     | usage                 | macOS | Windows | Linux |
| ---------------- | --------------------------------------------------- | --------------------- | ----- | ------- | ----- |
| **purgedl**      | remove old files in ~/Downloads                     | `purgedl`             | ✅     |         |       |
| **yutub**        | dowload youtube as .mp3                             | `yutub [URL]`         | ✅     |         |       |
| **svg2scalable** | make svg files scalable                             | `svg2scalable` [PATH] | ✅     |         |       |
| **ghloc**        | write the LOC of this project to its gh description | `ghloc`               | ✅     |         |       |
| **mac2vendor**   | return the vendor of a MAC address                  | `mac2vendor` [MAC]    | ✅     |         |       |

