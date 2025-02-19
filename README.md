# DLGSANet: Lightweight Dynamic Local and Global Self-Attention Networks for Image Super-Resolution

### [Project Page](https://neonleexiang.github.io/DLGSANet/) | [Paper (ArXiv)](https://arxiv.org/abs/2301.02031) | [Supplemental Material]()

**This repository is the official pytorch implementation of our paper, *DLGSANet: Lightweight Dynamic Local and Global Self-Attention Networks for Image Super-Resolution*.**

[Xiang Li](https://imag-njust.net/)<sup>1</sup>,
[Jinshan Pan](https://jspan.github.io/)<sup>1</sup>,
[Jinhui Tang](https://imag-njust.net/jinhui-tang/)<sup>1</sup>,
[Jiangxin Dong](https://imag-njust.net/jiangxin-dong/)<sup>1</sup> <br>

<sup>1</sup>[IMAG Lab](https://imag-njust.net/), Nanjing University of Science and Technology

> Abstract: We propose an effective lightweight dynamic local and global self-attention network (DLGSANet) to solve image super-resolution. Our method explores the properties of Transformers while having low computational costs. Motivated by the network designs of Transformers, we develop a simple yet effective multi-head dynamic local self-attention (MHDLSA) module to extract local features efficiently. In addition, we note that existing Transformers usually explore all similarities of the tokens between the queries and keys for the feature aggregation. However, not all the tokens from the queries are relevant to those in keys, using all the similarities does not effectively facilitate the high-resolution image reconstruction. To overcome this problem, we develop a sparse global self-attention (SparseGSA) module to select the most useful similarity values so that the most useful global features can be better utilized for the high-resolution image reconstruction. We develop a hybrid dynamic-Transformer block(HDTB) that integrates the MHDLSA and SparseGSA for both local and global feature exploration. To ease the network training, we formulate the HDTBs into a residual hybrid dynamic-Transformer group (RHDTG). By embedding the RHDTGs into an end-to-end trainable network, we show that our proposed method has fewer network parameters and lower computational costs while achieving competitive performance against state-of-the-art ones in terms of accuracy.

## Framework

![](./docs/media/dlgsanet_png.png)


---
## Contents

The contents of this repository are as follows:

1. [Dependencies](#Dependencies)
2. [Train](#Train)
3. [Test](#Test)

### Dependencies

> - Python
> - Pytorch (1.11 or 1.13)
> - basicsr
> - cupy-cuda

extra infos: 
> - [BasicSR](https://github.com/XPixelGroup/BasicSR)
> - [cupy](https://github.com/cupy/cupy)

For more details of the dependencies, please refer to `requirements.txt`

### Train

```
# For X2
sh ./demo_sbatch_file/SISR_ClassicDIV2K/train_SISR_ClassicDIV2K_Large_90C6G4B_DLGSANet_SRx2_scratch_img_size_48_lr5e_4.sh

# For X3
sh ./demo_sbatch_file/SISR_ClassicDIV2K/train_SISR_ClassicDIV2K_Large_90C6G4B_DLGSANet_SRx3_scratch_img_size_48_lr5e_4.sh

# For X4
sh ./demo_sbatch_file/SISR_ClassicDIV2K/train_SISR_ClassicDIV2K_Large_90C6G4B_DLGSANet_SRx4_scratch_img_size_48_lr5e_4.sh
```

### Test

```
# For X2
sh ./demo_sbatch_file/SISR_ClassicDIV2K/test_SISR_ClassicDIV2K_Large_90C6G4B_DLGSANet_SRx2_scratch_img_size_48_lr5e_4.sh

# For X3
sh ./demo_sbatch_file/SISR_ClassicDIV2K/test_SISR_ClassicDIV2K_Large_90C6G4B_DLGSANet_SRx3_scratch_img_size_48_lr5e_4.sh

# For X4
sh ./demo_sbatch_file/SISR_ClassicDIV2K/test_SISR_ClassicDIV2K_Large_90C6G4B_DLGSANet_SRx4_scratch_img_size_48_lr5e_4.sh

```

---

## Results

- **Pretrained models and visual results**

| Degradation |                                                                                                                                     Model Zoo                                                                                                                                      |                                                                                                                                   Visual Results                                                                                                                                    | 
| :----- |:----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------:|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------:|
| BI-Efficient SR |                                                                                      [Google Drive](https://drive.google.com/drive/folders/1jbh5hNP4AGhsMPabWG7yq1mIDa_FcriO?usp=drive_link)                                                                                       |                                                                                        [Google Drive](https://drive.google.com/file/d/1sseiCtqtrnsq2xJnODmrOtUzvYz0mFEU/view?usp=drive_link)                                                                                        |
| BI-Classic SR |                                                                                                                                       To-Do                                                                                                                                        |                                                                                                                                        To-Do                                                                                                                                        |
| BI-Classic SR (x4) |                                            [Google Drive](https://drive.google.com/drive/folders/1kqjoO7IEi7QmaOSEH37xKjRA_LcmL2eU?usp=sharing) / [Baidu Netdisk](https://pan.baidu.com/s/1PyArsdTVpQd8cK2UV65bxg?pwd=IMAG) `code:IMAG`                                            |                                           [Google Drive](https://drive.google.com/drive/folders/1dMiwuD4hyvz_E5R1Al848qQmIICAM3Os?usp=share_link) / [Baidu Netdisk](https://pan.baidu.com/s/1G_3mUUxImKScjVpDuDQnfg?pwd=IMAG) `code:IMAG`                                           |


- **Lightweight models PSNR**

Unfortunately, the lightweight models' pretrain models were lost. 
Additionally, the github project has not been updated for a year due to personal reasons.
Recently, I rebuilt the framework and used a single 3090GPU to retrain the lightweight models using the same training settings as the paper (16 batchsize).
The re-trained model and those in the study have a slightly varied PSNR (within 0.05dB) due to differences in devices and versions of Pytorch/Cuda.
New pre-train models and visual results will be added on Baidu Netdisk and Google Drive.
We recommend either training on your own for research purposes or using the new data from re-trained lightweight models.

`DLGSANet-Tiny`:

| model-scale      |        Set5        |       Set14        |       BSDS100      |      Urban100      |      Manga109       | 
|:-----------------|:------------------:|:------------------:|:------------------:|:------------------:|:-------------------:|
| `Tiny-x2(paper)` |  `38.16 / 0.9611`  |  `33.92 / 0.9202`  |  `32.26 / 0.9007`  |  `32.82 / 0.9343`  |  `39.14 / 0.9777`   | 
| `Tiny-x2`        | `38.1581 / 0.9615` | `33.8906 / 0.9200` | `32.2828 / 0.9017` | `32.8461 / 0.9343` | `39.1326 / 0.9780`  | 
| `Tiny-x3(paper)` |  `34.63 / 0.9288`  |  `30.57 / 0.8459`  |  `29.21 / 0.8083`  |  `28.69 / 0.8630`  |  `34.10 / 0.9480`   | 
| `Tiny-x3`        | `34.6197 / 0.9293` | `30.5370 / 0.8469` | `29.2335 / 0.8100` | `28.7829 / 0.8645` | `34.0463 / 0.9477`  | 
| `Tiny-x4(paper)` |  `32.46 / 0.8984`  |  `28.79 / 0.7861`  |  `27.70 / 0.7408`  |  `26.55 / 0.8002`  |  `30.98 / 0.9137`   | 
| `Tiny-x4`        | `32.4957 / 0.8992` | `28.7738 / 0.7862` | `27.7217 / 0.7426` | `26.5675 / 0.8006` | `30.9556 / 0.9142`  |

`DLGSANet-Light`:

| model-scale      |        Set5        |       Set14        |       BSDS100      |      Urban100      |      Manga109       | 
|:-----------------|:------------------:|:------------------:|:------------------:|:------------------:|:-------------------:|
| `Light-x2(paper)` |  `38.20 / 0.9612`  |  `33.89 / 0.9203`  |  `32.30 / 0.9012`  |  `32.94 / 0.9355`  |  `39.29 / 0.9780`  | 
| `Light-x2`        | `38.1577 / 0.9615` | `34.0453 / 0.9216` | `32.3058 / 0.9020` | `32.9323 / 0.9354` | `39.1995 / 0.9780` | 
| `Light-x3(paper)` |  `34.70 / 0.9295`  |  `30.58 / 0.8465`  |  `29.24 / 0.8089`  |  `28.83 / 0.8653`  |  `34.16 / 0.9483`  | 
| `Light-x3`        | `34.6697 / 0.9298` | `30.5621 / 0.8466` | `29.2484 / 0.8101` | `28.8239 / 0.8655` | `34.1938 / 0.9483` | 
| `Light-x4(paper)` |  `32.54 / 0.8993`  |  `28.84 / 0.7871`  |  `27.73 / 0.7415`  |  `26.66 / 0.8033`  |  `31.13 / 0.9161`  | 
| `Light-x4`        | `32.5333 / 0.8998` | `28.6401 / 0.7864` | `27.7299 / 0.7434` | `26.6702 / 0.8036` | `31.0196 / 0.9154` |




## Visual Results

![](./docs/media/img044_imgsli.png)

![](./docs/media/img073_imgsli.png)

![](./docs/media/img095_imgsli.png)


---


## To Do

Release pre-trained models of regular models

Release the visual results of BI super-resolution


## Citation
If this work is helpful for your research, please consider citing the following BibTeX entry.
```
 @article{li2023dlgsanet,
      title={DLGSANet: Lightweight Dynamic Local and Global Self-Attention Networks for Image Super-Resolution}, 
      author={Li, Xiang and Pan, Jinshan and Tang, Jinhui and Dong, Jiangxin},
      journal={arXiv preprint arXiv:2301.02031},
      year={2023},
}
```

## Acknowledgement

The foundation for the training process is [BasicSR](https://github.com/XPixelGroup/BasicSR) , which profited from the outstanding contribution of [XPixelGroup](https://github.com/XPixelGroup) .

The following research forms the foundation for the MHDLSA implementation:

> _On the Connection between Local Attention and Dynamic Depth-wise Convolution_ [paper](https://arxiv.org/abs/2106.04263) [github](https://github.com/Atten4Vis/DemystifyLocalViT)

And the following research forms the foundation for the SparseGSA implementation:

> _Restormer: Efficient Transformer for High-Resolution Image Restoration_ [paper](https://arxiv.org/abs/2111.09881) [github](https://github.com/swz30/Restormer)

> _Improving Image Restoration by Revisiting Global Information Aggregation_ [paper](https://arxiv.org/abs/2112.04491) [github](https://github.com/megvii-research/TLC)


## Contact

This repo is currently maintained by Xiang Li ([@neonleexiang](https://github.com/NeonLeexiang)) and is for academic research use only. 
