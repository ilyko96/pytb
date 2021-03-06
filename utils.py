#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jan 14 23:01:57 2020

@author: spl
"""

import numpy as np
import re
import scipy.io as spio

def annotate_image(image, label, font_path=None, font_size=16, font_color=[1., 1., 1.]):
    from PIL import Image
    from PIL import ImageFont
    from PIL import ImageDraw

    if font_path is None:
        font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'

    mask = Image.fromarray(np.zeros(image.shape, dtype=np.uint8))
    draw = ImageDraw.Draw(mask)
    font = ImageFont.truetype(font_path, font_size)
    draw.text((0, 0), label, (255, 255, 255), font=font)
    mask = np.atleast_3d(np.array(mask, dtype=np.float)[:, :, 0] / 255.).astype(image.dtype)
    return (1 - mask) * image + mask * np.array(font_color).reshape(1, 1, -1)

def pad(image, new_width, new_height, new_num_channels=None, value=0., center=True):
    height, width = image.shape[:2]
    pad_width = new_width - width
    pad_height = new_height - height
    margins0 = [pad_height // 2, pad_height - pad_height // 2]
    margins1 = [pad_width // 2, pad_width - pad_width // 2]

    image = np.concatenate((value * np.ones((margins0[0],) + image.shape[1:4], dtype=image.dtype),
                            image,
                            value * np.ones((margins0[1],) + image.shape[1:4], dtype=image.dtype)), axis=0)
    image = np.concatenate((value * np.ones((image.shape[0], margins1[0]) + image.shape[2:4], dtype=image.dtype),
                            image,
                            value * np.ones((image.shape[0], margins1[1]) + image.shape[2:4], dtype=image.dtype)), axis=1)
    if not new_num_channels is None and image.shape[2] < new_num_channels:
        image = np.concatenate((image, value * np.ones(image.shape[:2] + (new_num_channels - image.shape[2]), dtype=image.dtype)), axis=2)

    return image

def collage(images, **kwargs):
    if isinstance(images, np.ndarray):
        if images.ndim == 4:
            images = [images[:, :, :, i] for i in range(images.shape[3])]
        else:
            images = [images]

    nims = len(images)

    nc = kwargs.get('nc', int(np.ceil(np.sqrt(nims))))  # number of columns
    nr = kwargs.get('nr', int(np.ceil(nims / nc)))  # number of rows
    bw = kwargs.get('bw', 0)  # border width
    transpose = kwargs.get('transpose', False)
    transposeIms = kwargs.get('transposeIms', False)

    if nr * nc < nims:
        nc = int(np.ceil(np.sqrt(nims)))
        nr = int(np.ceil(nims / nc))

    # pad array so it matches the product nc * nr
    padding = nc * nr - nims
    h, w, numChans = images[0].shape[:3]
    ims = images + [np.zeros((h, w, numChans))] * padding
    coll = np.stack(ims, axis=3)
    coll = np.reshape(coll, (h, w, numChans, nc, nr))
    # 0  1  2   3   4
    # y, x, ch, co, ro
    if bw:
        # pad each patch by border if requested
        coll = np.append(coll, np.zeros((bw,) + coll.shape[1: 5]), axis=0)
        coll = np.append(coll, np.zeros((coll.shape[0], bw) + coll.shape[2: 5]), axis=1)
    if transpose:
        nim0 = nr
        nim1 = nc
        if transposeIms:
            dim0 = w
            dim1 = h
            #                          nr w  nc h  ch
            coll = np.transpose(coll, (4, 1, 3, 0, 2))
        else:
            dim0 = h
            dim1 = w
            #                          nr h  nc w  ch
            coll = np.transpose(coll, (4, 0, 3, 1, 2))
    else:
        nim0 = nc
        nim1 = nr
        if transposeIms:
            dim0 = w
            dim1 = h
            #                          nc w  nr h  ch
            coll = np.transpose(coll, (3, 1, 4, 0, 2))
        else:
            dim0 = h
            dim1 = w
            #                          nc h  nr w  ch
            coll = np.transpose(coll, (3, 0, 4, 1, 2))
    coll = np.reshape(coll, ((dim0 + bw) * nim0, (dim1 + bw) * nim1, numChans))

    return coll

def loadmat(filename):
    """wrapper around scipy.io.loadmat that avoids conversion of nested matlab structs to np.arrays"""
    mat = spio.loadmat(filename, struct_as_record=False, squeeze_me=True)
    for key in mat:
        if isinstance(mat[key], spio.matlab.mio5_params.mat_struct):
            mat[key] = to_dict(mat[key])
    return mat

def to_dict(matobj):
    """construct python dictionary from matobject"""
    output = {}
    for fn in matobj._fieldnames:
        val = matobj.__dict__[fn]
        if isinstance(val, spio.matlab.mio5_params.mat_struct):
            output[fn] = toDict(val)
        else:
            output[fn] = val
    return output

def strparse(strings, pattern, numeric=False, *args):
    res = [re.match(pattern, string) for string in strings]
    matching = np.nonzero(np.array([not r is None for r in res]))
    res = np.array(res)[matching]
    res = np.array([r.groups() for r in res])
    if numeric:
        print(len(args), args)
        if len(args) == 1:
            res = res.astype(args[0])
        elif len(args) == res.shape[1]:
            resOut = []
            for ci in range(len(args)):
                resOut.append(res[:, ci].astype(args[ci]))
            res = resOut
        elif len(args) != 0:
            raise Exception('number of type specifiers must equal the number of matching groups in the pattern!')
    return res

def read_exr(fname, outputType=np.float16):
    import pyexr
    file = pyexr.open(fname)
    channels = file.channel_map['all']
    pixels = file.get(group='all', precision=pyexr.FLOAT)
    return pixels, channels