# Devcontainer met FreeCAD via conda-forge + Python 3.12
FROM mambaorg/micromamba:1.5.8

# (A) Root nodig voor apt
USER root
RUN apt-get update \
    && apt-get install -y git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# (B) Terug naar normale user van de base image
USER micromamba

# FreeCAD + Python uit conda-forge
RUN micromamba install -y -n base -c conda-forge python=3.12 freecad \
    && micromamba clean -a -y

# uv installeren voor jouw Python deps
SHELL ["/bin/bash", "-lc"]
RUN pip install uv
ENV PATH="/home/micromamba/.local/bin:${PATH}"
ENV FREECAD_CMD=freecadcmd

WORKDIR /workspaces/fctostl

