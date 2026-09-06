#!/usr/bin/env python3

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import click
import yaml


CONFIG_DIR = Path.home() / ".config" / "blemdoc"
CONFIG_FILE = CONFIG_DIR / "blemdoc.yml"
DEFAULT_TEMPLATE_PATH = str(CONFIG_DIR / "templates")
BLEMLI_PURPLE = "8C1AC4"

# Shared preamble, materialized as common.tex in the template base (once,
# never overwritten) so every template can \input{common}.
COMMON_TEX = r"""% blemdoc shared preamble — \input{common} from any template
% (TEXINPUTS includes the template base dir)
\usepackage{fontspec}
\usepackage{enumitem}
\usepackage{parskip}
\usepackage{longtable,booktabs,array}
\usepackage{graphicx}

\setmainfont{JetBrainsMonoNL-Regular}[
  Extension=.ttf,
  Path=/Users/stephan/Library/Fonts/,
  BoldFont=JetBrainsMonoNL-Bold,
  ItalicFont=JetBrainsMonoNL-Italic,
  BoldItalicFont=JetBrainsMonoNL-BoldItalic,
]

\providecommand{\tightlist}{\setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}

% Keep list numbering in the same mono font and reduce indentation
\setlist[enumerate]{leftmargin=1.5em, labelsep=0.4em, font=\normalfont}
\setlist[itemize]{leftmargin=1.2em, labelsep=0.4em}

% Allow emergency line breaks for mono text
\sloppy
"""

# pandoc template syntax: $var$ for variables, $$ for literal $
DEFAULT_TEMPLATE = r"""\documentclass[a4paper,11pt]{article}
\usepackage{xcolor}
\usepackage{geometry}
\input{common}
\usepackage{hyperref}
\usepackage{titlesec}

\geometry{margin=2.5cm}

\definecolor{blemlipurple}{HTML}{""" + BLEMLI_PURPLE + r"""}

\hypersetup{
  colorlinks=true,
  linkcolor=blemlipurple,
  urlcolor=blemlipurple,
}

\titleformat{\section}{\large\bfseries\color{blemlipurple}}{}{0em}{}
\titleformat{\subsection}{\normalsize\bfseries\color{blemlipurple}}{}{0em}{}

$if(title)$
\title{$title$}
$endif$
$if(author)$
\author{$author$}
$endif$
$if(date)$
\date{$date$}
$endif$

\begin{document}

$if(title)$
\maketitle
$endif$

$body$

\end{document}
"""

DEFAULT_TEMPLATE_YML = """\
description: {name} template
# nup: 2x2
"""


def load_config():
    if CONFIG_FILE.exists():
        return yaml.safe_load(CONFIG_FILE.read_text()) or {}
    return {}


def save_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(yaml.dump(config, default_flow_style=False))


def get_template_base():
    config = load_config()
    if "template_path" not in config:
        click.echo("First run! Where should blemdoc store templates?")
        path = click.prompt("Template directory", default=DEFAULT_TEMPLATE_PATH)
        config["template_path"] = path
        save_config(config)
        click.echo(f"Saved config to {CONFIG_FILE}")
    return Path(config["template_path"]).expanduser()


def read_frontmatter(md_path):
    """Extract YAML frontmatter from a markdown file."""
    text = md_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        return yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return {}


def resolve_template_name(template_name, markdown):
    """Resolve template name from flag or frontmatter."""
    if template_name:
        return template_name
    fm = read_frontmatter(markdown)
    name = fm.get("template")
    if name:
        return name
    raise click.ClickException(
        "No template specified. Use -t or set 'template:' in frontmatter."
    )


def ensure_common(base):
    """Materialize the shared preamble once; never overwrite user edits."""
    common = base / "common.tex"
    if not common.exists():
        common.write_text(COMMON_TEX)


def load_template_yml(base, template_name):
    """Load template blemdoc.yml if it exists."""
    yml = base / template_name / f"{template_name}.blemdoc.yml"
    if yml.exists():
        return yaml.safe_load(yml.read_text()) or {}
    return {}


def nup_pdf(input_pdf, output_pdf, nup, duplex=False, delta=None, frame=False,
            margin=None):
    """Tile pages n-up on A4 using pdfpages.

    duplex: each source page fills its own sheet (page 1 x4, page 2 x4, ...)
    so double-sided printing keeps fronts and backs aligned.
    delta: gutter between tiles, e.g. "10mm 10mm" (space to cut/laminate).
    frame: hairline cut guide around each tile.
    margin: outer sheet margin in mm, e.g. "7mm" (keeps cut guides printable).
    """
    cols, rows = (int(n) for n in nup.lower().split("x"))
    opts = [f"nup={nup}"]
    if frame:
        opts.append("frame")
    if delta:
        opts.append(f"delta={delta}")
    if margin:
        m = float(str(margin).removesuffix("mm"))
        opts.append(f"scale={(210 - 2 * m) / 210:.4f}")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        shutil.copy2(input_pdf, tmpdir / "input.pdf")
        preamble = (
            "\\documentclass[a4paper]{article}\n"
            "\\usepackage{pdfpages}\n"
            "\\usepackage{xcolor}\n"
            "\\setlength{\\fboxrule}{0.2pt}\\setlength{\\fboxsep}{0pt}\n"
            "\\AtBeginDocument{\\color{black!40}}\n"
        )
        if duplex:
            pages = ",".join(["\\the\\pg"] * (cols * rows))
            body = (
                "\\newcount\\pg\\newcount\\total\n"
                "\\total=\\XeTeXpdfpagecount\"input.pdf\"\n"
                "\\pg=1\n"
                "\\loop\\ifnum\\pg<\\numexpr\\total+1\\relax\n"
                f"\\includepdf[{','.join(opts)},pages={{{pages}}}]{{input.pdf}}\n"
                "\\advance\\pg 1\n"
                "\\repeat\n"
            )
        else:
            body = f"\\includepdf[{','.join(opts)},pages=-]{{input.pdf}}\n"
        tex = tmpdir / "nup.tex"
        tex.write_text(
            preamble + "\\begin{document}\n" + body + "\\end{document}\n"
        )
        result = subprocess.run(
            ["xelatex", "-interaction=nonstopmode", "nup.tex"],
            cwd=tmpdir, capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise click.ClickException(f"nup tiling failed:\n{result.stderr}")
        shutil.copy2(tmpdir / "nup.pdf", output_pdf)


# Lua filter: horizontal rule (---) becomes a page break
HRULE_FILTER = "function HorizontalRule() return pandoc.RawBlock('latex', '\\\\clearpage') end\n"


def run_pandoc(markdown, template_file, output, extra_args=()):
    """Run pandoc to render markdown to PDF."""
    import os
    template_dir = Path(template_file).parent
    # template dir first, then template base (for shared includes like common.tex)
    env = {**os.environ, "TEXINPUTS": f"{template_dir}:{template_dir.parent}:"}
    result = subprocess.run(
        [
            "pandoc", str(markdown),
            f"--template={template_file}",
            "--pdf-engine=xelatex",
            "-o", str(output),
            *extra_args,
        ],
        capture_output=True, text=True,
        env=env,
    )
    if result.returncode != 0:
        raise click.ClickException(f"pandoc failed:\n{result.stderr}")


def check_deps():
    missing = [name for name in ("pandoc", "xelatex") if not shutil.which(name)]
    if missing:
        raise click.ClickException(f"Missing dependencies: {', '.join(missing)}")


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def blemdoc():
    """Render markdown files to PDF via LaTeX."""


@blemdoc.command()
@click.option("-t", "--template", "template_name", default=None, help="Template name (or set 'template:' in frontmatter)")
@click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Output PDF path")
@click.option("--nup", default=None, help="Tile sheets per page, e.g. 2x2")
@click.argument("markdown", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def render(template_name, output, markdown, nup):
    """Render a markdown file to PDF using a LaTeX template."""
    check_deps()

    template_name = resolve_template_name(template_name, markdown)
    base = get_template_base()
    template_file = base / template_name / "template.tex"
    if not template_file.exists():
        raise click.ClickException(
            f"Template '{template_name}' not found at {template_file}\n"
            f"Create it with: blemdoc template {template_name}"
        )

    ensure_common(base)
    tmpl_yml = load_template_yml(base, template_name)
    # nup from flag > blemdoc.yml > none
    nup = nup or tmpl_yml.get("nup")

    output = output or Path(f"{template_name}.pdf")

    extra_args = []
    if tmpl_yml.get("auto_date") and not read_frontmatter(markdown).get("date"):
        from datetime import date
        extra_args += ["-M", f"date={date.today().isoformat()}"]

    with tempfile.TemporaryDirectory() as tmpdir:
        if tmpl_yml.get("hrule_pagebreak"):
            lua = Path(tmpdir) / "hrule.lua"
            lua.write_text(HRULE_FILTER)
            extra_args.append(f"--lua-filter={lua}")

        if nup:
            # Render single sheet to temp, then tile
            tmp_pdf = Path(tmpdir) / "single.pdf"
            run_pandoc(markdown, template_file, tmp_pdf, extra_args)
            nup_pdf(
                tmp_pdf, output, nup,
                duplex=tmpl_yml.get("duplex", False),
                delta=tmpl_yml.get("delta"),
                frame=tmpl_yml.get("frame", False),
                margin=tmpl_yml.get("margin"),
            )
        else:
            run_pandoc(markdown, template_file, output, extra_args)

    click.echo(str(output.resolve()))


@blemdoc.command()
@click.argument("name")
def template(name):
    """Create a new template."""
    base = get_template_base()
    template_dir = base / name
    template_file = template_dir / "template.tex"

    if template_file.exists():
        raise click.ClickException(f"Template '{name}' already exists at {template_dir}")

    template_dir.mkdir(parents=True, exist_ok=True)
    ensure_common(base)
    template_file.write_text(DEFAULT_TEMPLATE)
    (template_dir / f"{name}.blemdoc.yml").write_text(
        DEFAULT_TEMPLATE_YML.format(name=name)
    )
    click.echo(f"Created template: {template_dir}")


@blemdoc.command(name="list")
def list_templates():
    """List available templates."""
    base = get_template_base()
    if not base.exists():
        click.echo("No templates found.")
        return
    templates = sorted(
        d.name for d in base.iterdir()
        if d.is_dir() and (d / "template.tex").exists()
    )
    if not templates:
        click.echo("No templates found.")
        return
    for name in templates:
        yml = base / name / f"{name}.blemdoc.yml"
        desc = ""
        if yml.exists():
            meta = yaml.safe_load(yml.read_text()) or {}
            desc = meta.get("description", "")
        click.echo(f"  {name}" + (f"  - {desc}" if desc else ""))


if __name__ == "__main__":
    blemdoc()
