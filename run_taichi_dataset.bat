@echo off
call D:\Miniconda\Scripts\activate.bat wham_gmr

set OUTPUT_ROOT=output/taichi_dataset
set ROBOT=unitree_g1
set RECORD_GMRVIDEO=1
set RECORD_WHAMVIDEO=0
set VIDEO=examples/taichi_dataset.mp4

powershell -NoProfile -ExecutionPolicy Bypass -File run.ps1
