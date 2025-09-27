# Devcontainer met FreeCAD via conda-forge + Python 3.12
FROM mambaorg/micromamba:1.5.8

# Maak conda-omgeving met FreeCAD + Python
RUN micromamba install -y -n base -c conda-forge python=3.12 freecad && \
    micromamba clean -a -y

# Handige tools
SHELL ["/bin/bash", "-lc"]
RUN apt-get update && apt-get install -y git curl ca-certificates && rm -rf /var/lib/apt/lists/*

# uv voor snelle Python dependency management
RUN pip install uv

# Project werkmap (VS Code mount hier de repo)
WORKDIR /workspaces/fc2stl

# Voor jouw CLI shim; fc2stl detecteert dit automatisch
ENV FREECAD_CMD=freecadcmd
