"""
    code based on :
        -[basicsr SwinIR] github: https://github.com/XPixelGroup/BasicSR/blob/master/basicsr/archs/swinir_arch.py
        -[Restormer] github: https://github.com/swz30/Restormer
"""

"""
@inproceedings{Zamir2021Restormer,
    title={Restormer: Efficient Transformer for High-Resolution Image Restoration}, 
    author={Syed Waqas Zamir and Aditya Arora and Salman Khan and Munawar Hayat 
            and Fahad Shahbaz Khan and Ming-Hsuan Yang},
    booktitle={CVPR},
    year={2022}
}


@article{liang2021swinir,
  title={SwinIR: Image Restoration Using Swin Transformer},
  author={Liang, Jingyun and Cao, Jiezhang and Sun, Guolei and Zhang, Kai and Van Gool, Luc and Timofte, Radu},
  journal={arXiv preprint arXiv:2108.10257},
  year={2021}
}
"""


import math
import torch
import torch.nn as nn
import torch.utils.checkpoint as checkpoint

from basicsr.utils.registry import ARCH_REGISTRY

from .arch_util import to_2tuple, trunc_normal_

from collections import OrderedDict

# for restormer
import numbers
from pdb import set_trace as stx

from einops import rearrange

# for idynamic
from .dlgsanet_idynamicdwconv_util import *


# ---------------------------------------------------------------------------------------------------------------------
# Layer Norm
def to_3d(x):
    return rearrange(x, 'b c h w -> b (h w) c')


def to_4d(x, h, w):
    return rearrange(x, 'b (h w) c -> b c h w', h=h, w=w)


class BiasFree_LayerNorm(nn.Module):
    def __init__(self, normalized_shape):
        super(BiasFree_LayerNorm, self).__init__()
        if isinstance(normalized_shape, numbers.Integral):
            normalized_shape = (normalized_shape,)
        normalized_shape = torch.Size(normalized_shape)

        assert len(normalized_shape) == 1

        self.weight = nn.Parameter(torch.ones(normalized_shape))
        self.normalized_shape = normalized_shape

    def forward(self, x):
        sigma = x.var(-1, keepdim=True, unbiased=False)
        return x / torch.sqrt(sigma+1e-5) * self.weight


class WithBias_LayerNorm(nn.Module):
    def __init__(self, normalized_shape):
        super(WithBias_LayerNorm, self).__init__()
        if isinstance(normalized_shape, numbers.Integral):
            normalized_shape = (normalized_shape,)
        normalized_shape = torch.Size(normalized_shape)

        assert len(normalized_shape) == 1

        self.weight = nn.Parameter(torch.ones(normalized_shape))
        self.bias = nn.Parameter(torch.zeros(normalized_shape))
        self.normalized_shape = normalized_shape

    def forward(self, x):
        mu = x.mean(-1, keepdim=True)
        sigma = x.var(-1, keepdim=True, unbiased=False)
        return (x - mu) / torch.sqrt(sigma+1e-5) * self.weight + self.bias


class LayerNorm(nn.Module):
    def __init__(self, dim, LayerNorm_type):
        super(LayerNorm, self).__init__()
        if LayerNorm_type =='BiasFree':
            self.body = BiasFree_LayerNorm(dim)
        else:
            self.body = WithBias_LayerNorm(dim)

    def forward(self, x):
        h, w = x.shape[-2:]
        return to_4d(self.body(to_3d(x)), h, w)
# ---------------------------------------------------------------------------------------------------------------------


# ---------------------------------------------------------------------------------------------------------------------
# Overlapped image patch embedding with 3x3 Conv
class OverlapPatchEmbed(nn.Module):
    def __init__(self, in_c=3, embed_dim=48, bias=False):    # for better performance and less params we set bias=False
        super(OverlapPatchEmbed, self).__init__()
        self.proj = nn.Conv2d(in_c, embed_dim, kernel_size=3, stride=1, padding=1, bias=bias)

    def forward(self, x):
        x = self.proj(x)
        return x
# ---------------------------------------------------------------------------------------------------------------------


# ---------------------------------------------------------------------------------------------------------------------
# FFN
class FeedForward(nn.Module):
    """
        GDFN in Restormer: [github] https://github.com/swz30/Restormer
    """
    def __init__(self, dim, ffn_expansion_factor, bias, input_resolution=None):
        super(FeedForward, self).__init__()

        self.input_resolution = input_resolution
        self.dim = dim
        self.ffn_expansion_factor = ffn_expansion_factor

        hidden_features = int(dim*ffn_expansion_factor)
        self.project_in = nn.Conv2d(dim, hidden_features*2, kernel_size=1, bias=bias)
        self.dwconv = nn.Conv2d(hidden_features*2, hidden_features*2, kernel_size=3, stride=1, padding=1, groups=hidden_features*2, bias=bias)
        self.project_out = nn.Conv2d(hidden_features, dim, kernel_size=1, bias=bias)

    def forward(self, x):
        x = self.project_in(x)
        x1, x2 = self.dwconv(x).chunk(2, dim=1)
        x = F.gelu(x1) * x2
        x = self.project_out(x)
        return x

    def flops(self):
        h, w = self.input_resolution
        N = h*w
        flops = 0

        flops += N * self.dim * self.dim * self.ffn_expansion_factor * 2
        flops += self.dim * self.ffn_expansion_factor * 2 * 9
        flops += N * self.dim * self.ffn_expansion_factor * self.dim
        return flops


# FFN
class BaseFeedForward(nn.Module):
    def __init__(self, dim, ffn_expansion_factor=2, bias=False):
        # base feed forward network in SwinIR
        super(BaseFeedForward, self).__init__()
        hidden_features = int(dim*ffn_expansion_factor)
        self.body = nn.Sequential(
            nn.Conv2d(dim, hidden_features, 1, bias=bias),
            nn.GELU(),
            nn.Conv2d(hidden_features, dim, 1, bias=bias),
        )

    def forward(self, x):
        # shortcut outside
        return self.body(x)
# ---------------------------------------------------------------------------------------------------------------------


# ---------------------------------------------------------------------------------------------------------------------
# IDynamicDWConvBlock
class IDynamicDWConvBlock(nn.Module):
    """
        code based on: [github] https://github.com/Atten4Vis/DemystifyLocalViT/blob/master/models/dwnet.py
        but we remove reductive Norm Layers and Activation Layers for better performance in SR-task
    """
    def __init__(self, dim, window_size, dynamic=True, heads=None, bias=True, input_resolution=None):
        super().__init__()

        # for flops counting
        self.input_resolution = input_resolution

        self.dim = dim
        self.window_size = window_size  # Wh, Ww
        self.dynamic = dynamic
        self.heads = heads

        # pw-linear
        # in pw-linear layer we inherit settings from DWBlock. Set bias=False
        self.conv0 = nn.Conv2d(dim, dim, 1, bias=False)
        self.conv1 = nn.Conv2d(dim, dim, 1, bias=False)

        if dynamic:
            self.conv = IDynamicDWConv(dim, kernel_size=window_size, group_channels=heads, bias=bias)
        else:
            self.conv = nn.Conv2d(dim, dim, kernel_size=window_size, stride=1, padding=window_size // 2, groups=dim, bias=bias)

    def forward(self, x):
        # shortcut outside the block
        x = self.conv0(x)
        x = self.conv(x)
        x = self.conv1(x)
        return x

    def flops(self):
        # calculate flops for windows with token length of N
        h, w = self.input_resolution
        N = h * w

        flops = 0
        # x = self.conv0(x)
        flops += N * self.dim * self.dim

        # x = self.conv(x)
        if self.dynamic:
            flops += (N * self.dim * self.dim / 4 + N * self.dim * self.window_size * self.window_size + N * self.dim / 4 * self.dim / self.heads * self.window_size * self.window_size)

        flops += N * self.dim * self.window_size * self.window_size
        #  x = self.conv2(x)
        flops += N * self.dim * self.dim
        return flops


# ---------------------------------------------------------------------------------------------------------------------
##########################################################################
# ## Multi-DConv Head Transposed Self-Attention (MDTA)
class Attention(nn.Module):
    """
        MDTA in Restormer: [github] https://github.com/swz30/Restormer
        TLC: [github] https://github.com/megvii-research/TLC
        We use TLC-Restormer in forward function and only use it in test mode
    """
    def __init__(self, dim, num_heads, bias, tlc_flag=True, tlc_kernel=48, input_resolution=None):
        super(Attention, self).__init__()
        self.tlc_flag = tlc_flag    # TLC flag for validation and test

        self.dim = dim
        self.input_resolution = input_resolution

        self.num_heads = num_heads
        self.temperature = nn.Parameter(torch.ones(num_heads, 1, 1))

        self.qkv = nn.Conv2d(dim, dim * 3, kernel_size=1, bias=bias)
        self.qkv_dwconv = nn.Conv2d(dim * 3, dim * 3, kernel_size=3, stride=1, padding=1, groups=dim * 3, bias=bias)
        self.project_out = nn.Conv2d(dim, dim, kernel_size=1, bias=bias)
        self.softmax = nn.Softmax(dim=-1)

        # tlc kernel
        self.kernel_size = [tlc_kernel, tlc_kernel]

    def _forward(self, qkv):
        q, k, v = qkv.chunk(3, dim=1)

        q = rearrange(q, 'b (head c) h w -> b head c (h w)', head=self.num_heads)
        k = rearrange(k, 'b (head c) h w -> b head c (h w)', head=self.num_heads)
        v = rearrange(v, 'b (head c) h w -> b head c (h w)', head=self.num_heads)

        q = torch.nn.functional.normalize(q, dim=-1)
        k = torch.nn.functional.normalize(k, dim=-1)

        attn = (q @ k.transpose(-2, -1)) * self.temperature

        # attn = attn.softmax(dim=-1)
        attn = self.softmax(attn)

        out = (attn @ v)
        return out

    def forward(self, x):
        b, c, h, w = x.shape

        qkv = self.qkv_dwconv(self.qkv(x))

        if self.training or not self.tlc_flag:
            out = self._forward(qkv)
            out = rearrange(out, 'b head c (h w) -> b (head c) h w', head=self.num_heads, h=h, w=w)

            out = self.project_out(out)
            return out

        # Then we use the TLC methods in test mode or validation
        qkv = self.grids(qkv)  # convert to local windows
        out = self._forward(qkv)
        out = rearrange(out, 'b head c (h w) -> b (head c) h w', head=self.num_heads, h=qkv.shape[-2], w=qkv.shape[-1])
        out = self.grids_inverse(out)  # reverse

        out = self.project_out(out)
        return out

    # Code from [megvii-research/TLC] https://github.com/megvii-research/TLC
    def grids(self, x):
        b, c, h, w = x.shape
        self.original_size = (b, c // 3, h, w)
        assert b == 1
        k1, k2 = self.kernel_size
        k1 = min(h, k1)
        k2 = min(w, k2)
        num_row = (h - 1) // k1 + 1
        num_col = (w - 1) // k2 + 1
        self.nr = num_row
        self.nc = num_col

        import math
        step_j = k2 if num_col == 1 else math.ceil((w - k2) / (num_col - 1) - 1e-8)
        step_i = k1 if num_row == 1 else math.ceil((h - k1) / (num_row - 1) - 1e-8)

        parts = []
        idxes = []
        i = 0  # 0~h-1
        last_i = False
        while i < h and not last_i:
            j = 0
            if i + k1 >= h:
                i = h - k1
                last_i = True
            last_j = False
            while j < w and not last_j:
                if j + k2 >= w:
                    j = w - k2
                    last_j = True
                parts.append(x[:, :, i:i + k1, j:j + k2])
                idxes.append({'i': i, 'j': j})
                j = j + step_j
            i = i + step_i

        parts = torch.cat(parts, dim=0)
        self.idxes = idxes
        return parts

    def grids_inverse(self, outs):
        preds = torch.zeros(self.original_size).to(outs.device)
        b, c, h, w = self.original_size

        count_mt = torch.zeros((b, 1, h, w)).to(outs.device)
        k1, k2 = self.kernel_size
        k1 = min(h, k1)
        k2 = min(w, k2)

        for cnt, each_idx in enumerate(self.idxes):
            i = each_idx['i']
            j = each_idx['j']
            preds[0, :, i:i + k1, j:j + k2] += outs[cnt, :, :, :]
            count_mt[0, 0, i:i + k1, j:j + k2] += 1.

        del outs
        torch.cuda.empty_cache()
        return preds / count_mt

    def flops(self):
        # calculate flops for 1 window with token length of N
        h, w = self.input_resolution
        N = h * w

        flops = 0
        # x = self.qkv(x)
        flops += N * self.dim * self.dim * 3
        # x = self.qkv_dwconv(x)
        flops += N * self.dim * 3 * 9

        # qkv
        # CxC
        N_k = self.kernel_size[0] * self.kernel_size[1]
        N_num = ((h - 1)//self.kernel_size[0] + 1) * ((w - 1) // self.kernel_size[1] + 1)

        flops += N_num * self.num_heads * self.dim // self.num_heads * N_k * self.dim // self.num_heads
        # CxN CxC
        flops += N_num * self.num_heads * self.dim // self.num_heads * self.dim // self.num_heads * N_k

        # x = self.project_out(x)
        flops += N * self.dim * self.dim
        return flops


class SparseAttention(nn.Module):
    """
        SparseGSA is based on MDTA
        MDTA in Restormer: [github] https://github.com/swz30/Restormer
        TLC: [github] https://github.com/megvii-research/TLC
        We use TLC-Restormer in forward function and only use it in test mode
    """
    def __init__(self, dim, num_heads, bias, tlc_flag=True, tlc_kernel=48, activation='relu', input_resolution=None):
        super(SparseAttention, self).__init__()
        self.tlc_flag = tlc_flag    # TLC flag for validation and test

        self.dim = dim
        self.input_resolution = input_resolution

        self.num_heads = num_heads
        self.temperature = nn.Parameter(torch.ones(num_heads, 1, 1))

        self.qkv = nn.Conv2d(dim, dim * 3, kernel_size=1, bias=bias)
        self.qkv_dwconv = nn.Conv2d(dim * 3, dim * 3, kernel_size=3, stride=1, padding=1, groups=dim * 3, bias=bias)
        self.project_out = nn.Conv2d(dim, dim, kernel_size=1, bias=bias)

        self.act = nn.Identity()

        # ['gelu', 'sigmoid'] is for ablation study
        if activation == 'relu':
            self.act = nn.ReLU()
        elif activation == 'gelu':
            self.act = nn.GELU()
        elif activation == 'sigmoid':
            self.act = nn.Sigmoid()

        # [x2, x3, x4] -> [96, 72, 48]
        self.kernel_size = [tlc_kernel, tlc_kernel]

    def _forward(self, qkv):
        q, k, v = qkv.chunk(3, dim=1)

        q = rearrange(q, 'b (head c) h w -> b head c (h w)', head=self.num_heads)
        k = rearrange(k, 'b (head c) h w -> b head c (h w)', head=self.num_heads)
        v = rearrange(v, 'b (head c) h w -> b head c (h w)', head=self.num_heads)

        q = torch.nn.functional.normalize(q, dim=-1)
        k = torch.nn.functional.normalize(k, dim=-1)

        attn = (q @ k.transpose(-2, -1)) * self.temperature

        # attn = attn.softmax(dim=-1)
        attn = self.act(attn)     # Sparse Attention due to ReLU's property

        out = (attn @ v)

        return out

    def forward(self, x):
        b, c, h, w = x.shape

        qkv = self.qkv_dwconv(self.qkv(x))

        if self.training or not self.tlc_flag:
            out = self._forward(qkv)
            out = rearrange(out, 'b head c (h w) -> b (head c) h w', head=self.num_heads, h=h, w=w)

            out = self.project_out(out)
            return out

        # Then we use the TLC methods in test mode
        qkv = self.grids(qkv)  # convert to local windows
        out = self._forward(qkv)
        out = rearrange(out, 'b head c (h w) -> b (head c) h w', head=self.num_heads, h=qkv.shape[-2], w=qkv.shape[-1])
        out = self.grids_inverse(out)  # reverse

        out = self.project_out(out)
        return out

    # Code from [megvii-research/TLC] https://github.com/megvii-research/TLC
    def grids(self, x):
        b, c, h, w = x.shape
        self.original_size = (b, c // 3, h, w)
        assert b == 1
        k1, k2 = self.kernel_size
        k1 = min(h, k1)
        k2 = min(w, k2)
        num_row = (h - 1) // k1 + 1
        num_col = (w - 1) // k2 + 1
        self.nr = num_row
        self.nc = num_col

        import math
        step_j = k2 if num_col == 1 else math.ceil((w - k2) / (num_col - 1) - 1e-8)
        step_i = k1 if num_row == 1 else math.ceil((h - k1) / (num_row - 1) - 1e-8)

        parts = []
        idxes = []
        i = 0  # 0~h-1
        last_i = False
        while i < h and not last_i:
            j = 0
            if i + k1 >= h:
                i = h - k1
                last_i = True
            last_j = False
            while j < w and not last_j:
                if j + k2 >= w:
                    j = w - k2
                    last_j = True
                parts.append(x[:, :, i:i + k1, j:j + k2])
                idxes.append({'i': i, 'j': j})
                j = j + step_j
            i = i + step_i

        parts = torch.cat(parts, dim=0)
        self.idxes = idxes
        return parts

    def grids_inverse(self, outs):
        preds = torch.zeros(self.original_size).to(outs.device)
        b, c, h, w = self.original_size

        count_mt = torch.zeros((b, 1, h, w)).to(outs.device)
        k1, k2 = self.kernel_size
        k1 = min(h, k1)
        k2 = min(w, k2)

        for cnt, each_idx in enumerate(self.idxes):
            i = each_idx['i']
            j = each_idx['j']
            preds[0, :, i:i + k1, j:j + k2] += outs[cnt, :, :, :]
            count_mt[0, 0, i:i + k1, j:j + k2] += 1.

        del outs
        torch.cuda.empty_cache()
        return preds / count_mt

    def flops(self):
        # calculate flops for window with token length of N
        h, w = self.input_resolution
        N = h * w

        flops = 0
        # x = self.qkv(x)
        flops += N * self.dim * self.dim * 3
        # x = self.qkv_dwconv(x)
        flops += N * self.dim * 3 * 9

        # qkv
        # CxC
        N_k = self.kernel_size[0] * self.kernel_size[1]
        N_num = ((h - 1)//self.kernel_size[0] + 1) * ((w - 1) // self.kernel_size[1] + 1)

        flops += N_num * self.num_heads * self.dim // self.num_heads * N_k * self.dim // self.num_heads
        # CxN CxC
        flops += N_num * self.num_heads * self.dim // self.num_heads * self.dim // self.num_heads * N_k

        # x = self.project_out(x)
        flops += N * self.dim * self.dim
        return flops
# ---------------------------------------------------------------------------------------------------------------------


# ---------------------------------------------------------------------------------------------------------------------
# IDynamicDWBlock with GDFN
class IDynamicLayerBlock(nn.Module):
    def __init__(self, dim, window_size=7, idynamic_num_heads=6, idynamic_ffn_type='GDFN', idynamic_ffn_expansion_factor=2., idynamic=True, input_resolution=None):
        super(IDynamicLayerBlock, self).__init__()

        self.dim = dim
        self.input_resolution = input_resolution

        self.norm1 = LayerNorm(dim, LayerNorm_type='WithBias')

        # IDynamic Local Feature Calculate
        self.IDynamicDWConv = IDynamicDWConvBlock(dim, window_size=window_size, dynamic=idynamic, heads=idynamic_num_heads, input_resolution=input_resolution)

        self.norm2 = LayerNorm(dim, LayerNorm_type='WithBias')

        # FeedForward Network
        if idynamic_ffn_type == 'GDFN':
            self.IDynamic_ffn = FeedForward(dim, ffn_expansion_factor=idynamic_ffn_expansion_factor, bias=False, input_resolution=input_resolution)
        elif idynamic_ffn_type == 'BaseFFN':
            self.IDynamic_ffn = BaseFeedForward(dim, ffn_expansion_factor=idynamic_ffn_expansion_factor, bias=True)
        else:
            raise NotImplementedError(f'Not supported FeedForward Net type{idynamic_ffn_type}')

    def forward(self, x):
        x = self.IDynamicDWConv(self.norm1(x)) + x
        x = self.IDynamic_ffn(self.norm2(x)) + x
        return x

    def flops(self):
        flops = 0
        h, w = self.input_resolution
        flops += self.dim * h * w
        flops += self.dim * h * w

        flops += self.IDynamicDWConv.flops()
        flops += self.IDynamic_ffn.flops()
        return flops


class RestormerLayerBlock(nn.Module):
    def __init__(self, dim, restormer_num_heads=6, restormer_ffn_type='GDFN', restormer_ffn_expansion_factor=2., tlc_flag=True, tlc_kernel=48, input_resolution=None):
        super(RestormerLayerBlock, self).__init__()

        self.dim = dim
        self.input_resolution = input_resolution

        self.norm3 = LayerNorm(dim, LayerNorm_type='WithBias')

        # Restormer Attention
        self.restormer_attn = Attention(dim, num_heads=restormer_num_heads, bias=False, tlc_flag=tlc_flag, tlc_kernel=tlc_kernel, input_resolution=input_resolution)

        self.norm4 = LayerNorm(dim, LayerNorm_type='WithBias')

        # Restormer FeedForward
        if restormer_ffn_type == 'GDFN':
            self.restormer_ffn = FeedForward(dim, ffn_expansion_factor=restormer_ffn_expansion_factor, bias=False, input_resolution=input_resolution)
        elif restormer_ffn_type == 'BaseFFN':
            self.restormer_ffn = BaseFeedForward(dim, ffn_expansion_factor=restormer_ffn_expansion_factor, bias=True)
        else:
            raise NotImplementedError(f'Not supported FeedForward Net type{restormer_ffn_type}')

    def forward(self, x):
        x = self.restormer_attn(self.norm3(x)) + x
        x = self.restormer_ffn(self.norm4(x)) + x
        return x

    def flops(self):
        flops = 0
        h, w = self.input_resolution
        flops += self.dim * h * w
        flops += self.dim * h * w

        flops += self.restormer_attn.flops()
        flops += self.restormer_ffn.flops()
        return flops


class SparseAttentionLayerBlock(nn.Module):
    def __init__(self, dim, restormer_num_heads=6, restormer_ffn_type='GDFN', restormer_ffn_expansion_factor=2., tlc_flag=True, tlc_kernel=48, activation='relu', input_resolution=None):
        super(SparseAttentionLayerBlock, self).__init__()

        self.dim = dim
        self.input_resolution = input_resolution

        self.norm3 = LayerNorm(dim, LayerNorm_type='WithBias')

        # We use SparseGSA inplace MDTA
        self.restormer_attn = SparseAttention(dim, num_heads=restormer_num_heads, bias=False, tlc_flag=tlc_flag, tlc_kernel=tlc_kernel, activation=activation, input_resolution=input_resolution)

        self.norm4 = LayerNorm(dim, LayerNorm_type='WithBias')

        # Restormer FeedForward
        if restormer_ffn_type == 'GDFN':
            # FIXME: new experiment, test bias
            self.restormer_ffn = FeedForward(dim, ffn_expansion_factor=restormer_ffn_expansion_factor, bias=False, input_resolution=input_resolution)
        elif restormer_ffn_type == 'BaseFFN':
            self.restormer_ffn = BaseFeedForward(dim, ffn_expansion_factor=restormer_ffn_expansion_factor, bias=True)
        else:
            raise NotImplementedError(f'Not supported FeedForward Net type{restormer_ffn_type}')

    def forward(self, x):
        x = self.restormer_attn(self.norm3(x)) + x
        x = self.restormer_ffn(self.norm4(x)) + x
        return x

    def flops(self):
        flops = 0
        h, w = self.input_resolution
        flops += self.dim * h * w
        flops += self.dim * h * w

        flops += self.restormer_attn.flops()
        flops += self.restormer_ffn.flops()
        return flops
# ---------------------------------------------------------------------------------------------------------------------


# ---------------------------------------------------------------------------------------------------------------------
# BuildBlocks
class BuildBlock(nn.Module):
    # Sorry for the redundant parameter setting
    # it is easier for ablation study while during experiment
    # if necessary it can be changed to **args
    def __init__(self, dim, blocks=3, buildblock_type='edge',
                 window_size=7, idynamic_num_heads=6, idynamic_ffn_type='GDFN', idynamic_ffn_expansion_factor=2., idynamic=True,
                 restormer_num_heads=6, restormer_ffn_type='GDFN', restormer_ffn_expansion_factor=2., tlc_flag=True, tlc_kernel=48, activation='relu', input_resolution=None
                 ):
        super(BuildBlock, self).__init__()

        self.input_resolution = input_resolution

        # those all for extra_repr
        # --------
        self.dim = dim
        self.blocks = blocks
        self.buildblock_type = buildblock_type
        self.window_size = window_size
        self.num_heads = (idynamic_num_heads, restormer_num_heads)
        self.ffn_type = (idynamic_ffn_type, restormer_ffn_type)
        self.ffn_expansion = (idynamic_ffn_expansion_factor, restormer_ffn_expansion_factor)
        self.idynamic = idynamic
        self.tlc = tlc_flag
        # ---------

        # buildblock body
        # ---------
        body = []
        if buildblock_type == 'edge':
            for _ in range(blocks):
                body.append(IDynamicLayerBlock(dim, window_size, idynamic_num_heads, idynamic_ffn_type, idynamic_ffn_expansion_factor, idynamic, input_resolution=input_resolution))
                body.append(RestormerLayerBlock(dim, restormer_num_heads, restormer_ffn_type, restormer_ffn_expansion_factor, tlc_flag, input_resolution=input_resolution))

        elif buildblock_type == 'sparseedge':
            for _ in range(blocks):
                body.append(IDynamicLayerBlock(dim, window_size, idynamic_num_heads, idynamic_ffn_type, idynamic_ffn_expansion_factor, idynamic, input_resolution=input_resolution))
                body.append(SparseAttentionLayerBlock(dim, restormer_num_heads, restormer_ffn_type, restormer_ffn_expansion_factor, tlc_flag, tlc_kernel, activation, input_resolution=input_resolution))

        elif buildblock_type == 'idynamic':
            for _ in range(blocks):
                body.append(IDynamicLayerBlock(dim, window_size, idynamic_num_heads, idynamic_ffn_type, idynamic_ffn_expansion_factor, idynamic))

        elif buildblock_type == 'restormer':
            for _ in range(blocks):
                body.append(RestormerLayerBlock(dim, restormer_num_heads, restormer_ffn_type, restormer_ffn_expansion_factor, tlc_flag))
        # --------

        body.append(nn.Conv2d(dim, dim, 3, 1, 1))   # as like SwinIR, we use one Conv3x3 layer after buildblock
        self.body = nn.Sequential(*body)

    def forward(self, x):
        return self.body(x) + x     # shortcut in buildblock

    def extra_repr(self) -> str:
        return f'dim={self.dim}, blocks={self.blocks}, buildblock_type={self.buildblock_type}, ' \
               f'window_size={self.window_size}, num_heads={self.num_heads}, ffn_type={self.ffn_type}, ' \
               f'ffn_expansion={self.ffn_expansion}, idynamic={self.idynamic}, tlc={self.tlc}'

    def flops(self):
        flops = 0
        h, w = self.input_resolution

        for i in range(len(self.body) - 1):
            flops += self.body[i].flops()

        flops += h*w * self.dim * self.dim * 9

        return flops
# ---------------------------------------------------------------------------------------------------------------------


# ---------------------------------------------------------------------------------------------------------------------
class UpsampleOneStep(nn.Sequential):
    """UpsampleOneStep module (the difference with Upsample is that it always only has 1conv + 1pixelshuffle)
       Used in lightweight SR to save parameters.

       but for our model, we give up Traditional Upsample and use UpsampleOneStep for better performance not only in
       lightweight SR model, Small/XSmall SR model, but also for our base model.

    Args:
        scale (int): Scale factor. Supported scales: 2^n and 3.
        num_feat (int): Channel number of intermediate features.

    """
    def __init__(self, scale, num_feat, num_out_ch, input_resolution=None):
        self.num_feat = num_feat
        self.input_resolution = input_resolution
        m = []
        m.append(nn.Conv2d(num_feat, (scale**2) * num_out_ch, 3, 1, 1))
        m.append(nn.PixelShuffle(scale))
        super(UpsampleOneStep, self).__init__(*m)

    def flops(self):
        h, w = self.input_resolution
        flops = h * w * self.num_feat * 3 * 9
        return flops


# Traditional Upsample from SwinIR EDSR RCAN
class Upsample(nn.Sequential):
    """Upsample module.

    Args:
        scale (int): Scale factor. Supported scales: 2^n and 3.
        num_feat (int): Channel number of intermediate features.
    """

    def __init__(self, scale, num_feat):
        m = []
        if (scale & (scale - 1)) == 0:  # scale = 2^n
            for _ in range(int(math.log(scale, 2))):
                m.append(nn.Conv2d(num_feat, 4 * num_feat, 3, 1, 1))
                m.append(nn.PixelShuffle(2))
        elif scale == 3:
            m.append(nn.Conv2d(num_feat, 9 * num_feat, 3, 1, 1))
            m.append(nn.PixelShuffle(3))
        else:
            raise ValueError(f'scale {scale} is not supported. Supported scales: 2^n and 3.')
        super(Upsample, self).__init__(*m)
# ---------------------------------------------------------------------------------------------------------------------


# ---------------------------------------------------------------------------------------------------------------------
# Network
@ARCH_REGISTRY.register()
class DLGSANet(nn.Module):
    r""" DLGSANet
        A PyTorch impl of : DLGSANet: Lightweight Dynamic Local and Global Self-Attention Network for Image Super-Resolution
        'IDynamic' using the idynamic transformer block
        'Restormer' using the Restormer transformer block
        'Edge' a new way inspired by EdgeViTs and EdgeNeXt
        'SparseEdge' a new way of using ReLU's properties for Sparse Attention

    Args:
        in_chans (int): Number of input image channels. Default: 3
        embed_dim (int): Patch embedding dimension. Default: 90
        depths (tuple(int)): Depth of each BuildBlock
        num_heads (tuple(int)): Number of attention heads in different layers
        window_size (int): Window size. Default: 7
        ffn_expansion_factor (float): Ratio of feedforward network hidden dim to embedding dim. Default: 2
        ffn_type (str): feedforward network type, such as GDFN and BaseFFN
        bias (bool): If True, add a learnable bias to layers. Default: True
        body_norm (bool): Normalization layer. Default: False
        idynamic (bool): using idynamic for local attention. Default: True
        tlc_flag (bool): using TLC during validation and test. Default: True
        tlc_kernel (int): TLC kernel_size [x2, x3, x4] -> [96, 72, 48]
        upscale: Upscale factor. 2/3/4 for image SR
        img_range: Image range. 1. or 255.
        upsampler: The reconstruction module. 'pixelshuffle'/'pixelshuffledirect'
    """

    def __init__(self,
                 in_chans=3,
                 dim=60,
                 groups=4,
                 blocks=3,
                 buildblock_type='edge',
                 window_size=7, idynamic_num_heads=6, idynamic_ffn_type='GDFN', idynamic_ffn_expansion_factor=2.,
                 idynamic=True,
                 restormer_num_heads=6, restormer_ffn_type='GDFN', restormer_ffn_expansion_factor=2., tlc_flag=True, tlc_kernel=48, activation='relu',
                 upscale=4,
                 img_range=1.,
                 upsampler='',
                 body_norm=False,
                 input_resolution=None,     # input_resolution = (height, width)
                 **kwargs):
        super(DLGSANet, self).__init__()

        # for flops counting
        self.dim = dim
        self.input_resolution = input_resolution

        # MeanShift for Image Input
        # ---------
        self.img_range = img_range
        if in_chans == 3:
            rgb_mean = (0.4488, 0.4371, 0.4040)
            self.mean = torch.Tensor(rgb_mean).view(1, 3, 1, 1)
        else:
            self.mean = torch.zeros(1, 1, 1, 1)
        # -----------

        # Upsample setting
        # -----------
        self.upscale = upscale
        self.upsampler = upsampler
        # -----------

        # ------------------------- 1, shallow feature extraction ------------------------- #
        # the overlap_embed: remember to set it into bias=False
        self.overlap_embed = nn.Sequential(OverlapPatchEmbed(in_chans, dim, bias=False))

        # ------------------------- 2, deep feature extraction ------------------------- #
        m_body = []

        # Base on the Transformer, When we use pre-norm we need to build a norm after the body block
        if body_norm:       # Base on the SwinIR model, there are LayerNorm Layers in PatchEmbed Layer between body
            m_body.append(LayerNorm(dim, LayerNorm_type='WithBias'))

        for i in range(groups):
            m_body.append(BuildBlock(dim, blocks, buildblock_type,
                 window_size, idynamic_num_heads, idynamic_ffn_type, idynamic_ffn_expansion_factor, idynamic,
                 restormer_num_heads, restormer_ffn_type, restormer_ffn_expansion_factor, tlc_flag, tlc_kernel, activation, input_resolution=input_resolution))

        if body_norm:
            m_body.append(LayerNorm(dim, LayerNorm_type='WithBias'))

        m_body.append(nn.Conv2d(dim, dim, kernel_size=(3, 3), padding=(1, 1)))

        self.deep_feature_extraction = nn.Sequential(*m_body)

        # ------------------------- 3, high quality image reconstruction ------------------------- #

        # setting for pixelshuffle for big model, but we only use pixelshuffledirect for all our model
        # -------
        num_feat = 64
        embed_dim = dim
        num_out_ch = in_chans
        # -------

        if self.upsampler == 'pixelshuffledirect':
            # for lightweight SR (to save parameters)
            self.upsample = UpsampleOneStep(upscale, embed_dim, num_out_ch, input_resolution=self.input_resolution)

        elif self.upsampler == 'pixelshuffle':
            # for classical SR
            self.conv_before_upsample = nn.Sequential(
                nn.Conv2d(embed_dim, num_feat, 3, 1, 1),
                nn.LeakyReLU(inplace=True)
            )
            self.upsample = Upsample(upscale, num_feat)
            self.conv_last = nn.Conv2d(num_feat, num_out_ch, 3, 1, 1)

        else:
            # for image denoising and JPEG compression artifact reduction
            self.conv_last = nn.Conv2d(embed_dim, num_out_ch, 3, 1, 1)

        self.apply(self._init_weights)

    def _init_weights(self, m):
        if isinstance(m, nn.Linear):
            trunc_normal_(m.weight, std=.02)
            if isinstance(m, nn.Linear) and m.bias is not None:
                nn.init.constant_(m.bias, 0)
        elif isinstance(m, nn.LayerNorm):
            nn.init.constant_(m.bias, 0)
            nn.init.constant_(m.weight, 1.0)

    @torch.jit.ignore
    def no_weight_decay(self):
        return {'absolute_pos_embed'}

    @torch.jit.ignore
    def no_weight_decay_keywords(self):
        return {'relative_position_bias_table'}

    def forward_features(self, x):
        pass    # all are in forward function including deep feature extraction

    def forward(self, x):
        self.mean = self.mean.type_as(x)
        x = (x - self.mean) * self.img_range

        if self.upsampler == 'pixelshuffledirect':
            # for lightweight SR
            x = self.overlap_embed(x)
            x = self.deep_feature_extraction(x) + x
            x = self.upsample(x)

        elif self.upsampler == 'pixelshuffle':
            # for classical SR
            x = self.overlap_embed(x)
            x = self.deep_feature_extraction(x) + x
            x = self.conv_before_upsample(x)
            x = self.conv_last(self.upsample(x))

        else:
            # for image denoising and JPEG compression artifact reduction
            x = self.overlap_embed(x)
            x = self.deep_feature_extraction(x) + x
            x = self.conv_last(x)

        x = x / self.img_range + self.mean

        return x

    def flops(self):
        flops = 0
        h, w = self.input_resolution

        # overlap_embed layer
        flops += h * w * 3 * self.dim * 9

        # BuildBlock:
        for i in range(len(self.deep_feature_extraction) - 1):
            flops += self.deep_feature_extraction[i].flops()

        # conv after body
        flops += h * w * 3 * self.dim * self.dim
        flops += self.upsample.flops()

        return flops


if __name__ == '__main__':
    # use fvcore for flops accounting
    # from fvcore.nn import FlopCountAnalysis, flop_count_str, flop_count_table

    upscale = 4
    # window_size = 8
    height = (1280 // upscale)
    width = (720 // upscale)
    window_size = 7
    idynamic_num_heads = 15
    restormer_num_heads = 15
    print(f'information of input: [upscale: {upscale}] [height: {height}] [weight: {width} \n')

    dim = 90
    groups = 6
    blocks = 4
    print(f'loading model TIPEIRNet with [dim: {dim}] [groups: {groups}] [blocks: {blocks} \n')
    model = DLGSANet(dim=dim, upscale=upscale, groups=groups, blocks=blocks, window_size=window_size, idynamic_num_heads=idynamic_num_heads, restormer_num_heads=restormer_num_heads, upsampler='pixelshuffledirect', input_resolution=(height, width))

    print('======'*50)
    print(model)

    print('======'*50)
    print('fvcore for model flops counting...' + '-'*50)
    x = torch.randn((1, 3, height, width))
    # x = model(x)

    net_params = sum(map(lambda x: x.numel(), model.parameters()))
    print(f"network params: {net_params}")
    print(height, width, model.flops() / 1e9)

    import numpy as np
    from torchvision.models import resnet50
    import torch
    from torch.backends import cudnn
    import tqdm

    cudnn.benchmark = True

    device = 'cuda:0'

    repetitions = 10

    # upscale = 4
    # window_size = 8
    # height = (1280 // upscale // window_size + 1) * window_size
    # width = (720 // upscale // window_size + 1) * window_size
    # model = SwinIR(
    #     upscale=4,
    #     img_size=(height, width),
    #     window_size=window_size,
    #     img_range=1.,
    #     depths=[6, 6, 6, 6, 6, 6],
    #     embed_dim=180,
    #     num_heads=[6, 6, 6, 6, 6, 6],
    #     mlp_ratio=2,
    #     upsampler='pixelshuffle').to(device)
    model = model.to(device)
    dummy_input = torch.rand(1, 3, height, width).to(device)

    # warm up
    print('warm up ...\n')
    with torch.no_grad():
        for _ in range(100):
            _ = model(dummy_input)

    # synchronize / wait for all the GPU process then back to cpu
    torch.cuda.synchronize()

    # testing CUDA Event
    starter, ender = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
    # initialize
    timings = np.zeros((repetitions, 1))

    print('testing ...\n')
    with torch.no_grad():
        for rep in tqdm.tqdm(range(repetitions)):
            starter.record()
            _ = model(dummy_input)
            ender.record()
            torch.cuda.synchronize()  # wait for ending
            curr_time = starter.elapsed_time(ender)  # from starter to ender (/ms)
            timings[rep] = curr_time

    avg = timings.sum() / repetitions
    print('\navg={}\n'.format(avg))

    # with torch.no_grad():
    #     flop = FlopCountAnalysis(model, x)
    #     print(flop_count_table(flop, max_depth=4, show_param_shapes=False))
    #     # print(flop_count_str(flop))
    #     print("Total", flop.total() / 1e9)
    #
    # print('======'*50)
    # print('check output shape: ')
    # print(x.shape)