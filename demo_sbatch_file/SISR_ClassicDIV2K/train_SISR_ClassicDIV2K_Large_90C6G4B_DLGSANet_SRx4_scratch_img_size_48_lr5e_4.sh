# environment testing
nvidia-smi
uname -a
cat /proc/version

cd ../../

python3 test_conda_env_setting.py

# training process based on BasicSR
# distribute
CUDA_VISIBLE_DEVICES=0,1 ./scripts/dist_train.sh 2 options/DLGSANet_SISR/train_SISR_ClassicDIV2K_Large_90C6G4B_DLGSANet_SRx4_scratch_img_size_48_lr5e_4.yml --debug

# CUDA_VISIBLE_DEVICES=0 python3 basicsr/train.py -opt options/DLGSANet/train_ClassicSR_Large_90C6G4B_DLGSANet_SRx4_scratch_img_size_48_lr5e_4.yml --debug
