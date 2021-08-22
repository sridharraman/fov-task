# FOV Task - Policy Modelling

## Introduction

The repository has been organised as follows:

data/ -- contains all the supply and demand data for the running of the model
  processed/ -- generated during the running of the model
docs/ -- contains model description
  presentations/ -- contains presentations (in PDF, PPTX) form for Academics and Decision-makers
transport_mode.py -- model script
requirements.txt -- list of python libraries for installation
log/ -- logging

## Installation

`pip install -r requirements.txt`

NOTE: Using conda/pipenv is recommended to have a separate environment. But it's not mandatory.

If using conda, these are the steps:

`conda create --name fov-task`

`conda activate fov-task`

`conda install pip`

`pip install -r requirements.txt`

## Model running

Run the model:

`python3 transport_mode.py`

The model runs all the scenarios as part of this script. This generates both charts and graphs along with terminal output. Multi-processing has been used to parallelise the rendering of charts. Stop the script by either closing all the charts or hard-stopping the script directly using Ctrl-C.
