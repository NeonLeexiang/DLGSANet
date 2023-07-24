nvidia-smi
uname -a
cat /proc/version

cd ../../

python3 test_conda_env_setting.py

CUDA_VISIBLE_DEVICES=0 python3 basicsr/test.py -opt options/DLGSANet_SISR/test_SISR_ClassicDIV2K_Large_90C6G4B_DLGSANet_SRx2_scratch_img_size_48_lr5e_4.yml


