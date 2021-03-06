# -*- coding: utf-8 -*-
"""
Created on Thu Oct 18 19:24:05 2018

@author: merzbach

"""

from datetime import datetime
from functools import wraps
import imageio
from IPython import get_ipython
import numpy as np
import sys
import traceback
import time
import types

import PyQt5.QtCore as QtCore
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QApplication, QCheckBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton, QShortcut, QSizePolicy, QSpacerItem, QVBoxLayout, QWidget

import matplotlib
try:
    matplotlib.use('Qt5Agg')
except:
    pass
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from matplotlib.figure import Figure
from matplotlib.axes import Axes
from matplotlib.transforms import Bbox

from matplotlib import pyplot as plt
import matplotlib.gridspec as gridspec

import torch

from pytb.utils import pad

'''
def MyPyQtSlot(*args):
    if len(args) == 0 or isinstance(args[0], types.FunctionType):
        args = []
    @QtCore.pyqtSlot(*args)
    def slotdecorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                func(*args)
            except:
                print("Uncaught Exception in slot")
                traceback.print_exc()
        return wrapper
    return slotdecorator
'''

class iv(QMainWindow):
    zoom_factor = 1.1
    x_zoom = True
    y_zoom = True
    x_stop_at_orig = True
    y_stop_at_orig = True

    def __init__(self, *args, **kwargs):
        app = QtCore.QCoreApplication.instance()
        if app is None:
            app = QApplication([''])
        QMainWindow.__init__(self, parent=None)

        timestamp = datetime.now().strftime("%y%m%d_%H%M%S")
        self.setWindowTitle('iv ' + timestamp)
        
        shell = get_ipython()
        shell.magic('%matplotlib qt')

        # store list of input images
        if len(args) == 1 and isinstance(args[0], torch.Tensor):
            # handle torch.Tensor input
            if args[0].ndim <= 3:
                self.images = [args[0].detach().cpu().numpy()]
            elif args[0].ndim == 4:
                # probably a torch tensor with dimensions [batch, channels, y, x]
                self.images = [[]] * args[0].shape[0]
                tmp = args[0].detach().cpu().numpy().transpose((2, 3, 1, 0))
                for imind in range(tmp.shape[3]):
                    self.images[imind] = tmp[:, :, :, imind]
                del tmp
            else:
                raise Exception('torch tensors can at most have 4 dimensions')
        
        elif len(args) == 1 and isinstance(args[0], np.ndarray) and len(args[0].shape) == 4:
            # handle 4D numpy.ndarray input by slicing in 4th dimension
            self.images = [[]] * args[0].shape[3]
            for imind in range(args[0].shape[3]):
                self.images[imind] = args[0][:, :, :, imind]
        
        elif len(args) == 1 and (isinstance(args[0], list) or isinstance(args[0], tuple)):
            self.images = list(args[0])
        
        else:
            self.images = list(args)
        
        for imind in range(len(self.images)):
            if isinstance(self.images[imind], torch.Tensor):
                self.images[imind] = self.images[imind].detach().cpu().numpy()
                if self.images[imind].ndim == 4:
                    # probably a torch tensor with dimensions [batch, channels, y, x]
                    self.images[imind] = self.images[imind].transpose((2, 3, 1, 0))
                elif self.images[imind].ndim > 4:
                    raise Exception('torch tensors can at most have 4 dimensions')
                    
            self.images[imind] = np.atleast_3d(self.images[imind])
            if self.images[imind].shape[2] != 1 and self.images[imind].shape[2] != 3:
                if self.images[imind].ndim == 4:
                    
                    self.images[imind] = self.images[imind].transpose((2, 3, 1, 0))

        self.imind = 0 # currently selected image
        self.nims = len(self.images)
        self.scale = 1.
        self.gamma = 1.
        self.offset = 0.
        self.autoscalePrctile = 0.1
        self.autoscaleUsePrctiles = True
        self.autoscaleOnChange = False
        self.autoscalePerImg = False
        self.collageActive = False
        self.collageTranspose = False
        self.collageTransposeIms = False
        self.collage_nc = int(np.ceil(np.sqrt(self.nims)))
        self.collage_nr = int(np.ceil(self.nims / self.collage_nc))
        self.collage_border_width = 0
        self.collage_border_value = 0.
        self.crop        = kwargs.get('crop', False)
        self.crop_global = kwargs.get('crop_global', True)
        self.zoom_factor = 1.1
        self.x_zoom = True
        self.y_zoom = True
        self.x_stop_at_orig = True
        self.y_stop_at_orig = True
        self.annotate = False
        self.font_size = 12
        
        self.crop_bounds()
        self.initUI()
        
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        #plt.tight_layout()
        self.updateImage()
        if self.autoscaleOnChange:
            self.autoscale()
        self.cur_xlims = self.ih.axes.axis()[0 : 2]
        self.cur_ylims = self.ih.axes.axis()[2 :]
        
        self.mouse_down = 0
        self.x_start = 0
        self.y_start = 0
        self.cid = self.fig.canvas.mpl_connect('button_press_event', self.onclick)
        self.cid = self.fig.canvas.mpl_connect('button_release_event', self.onrelease)
        self.cid = self.fig.canvas.mpl_connect('motion_notify_event', self.onmotion)
        self.cid = self.fig.canvas.mpl_connect('key_press_event', self.keyPressEvent)#onkeypress)
        self.cid = self.fig.canvas.mpl_connect('key_release_event', self.keyReleaseEvent)#onkeyrelease)
        self.cid = self.fig.canvas.mpl_connect('scroll_event', self.onscroll)
        self.alt = False
        self.control = False
        self.shift = False
        self.prev_delta_x = 0
        self.prev_delta_y = 0
        #plt.show(block=True)
        #plt.pause(10)
        #plt.show(block=False)
        
        self.setWindowModality(QtCore.Qt.WindowModal)
        self.show()

    def crop_bounds(self):
        # pre-compute cropping bounds (tight bounding box around non-zero pixels)
        nzs = [np.where(np.sum(im, axis=2) > 0) for im in self.images]
        self.xmins = [np.min(nz[1]) if len(nz[1]) else 0 for nz in nzs]
        self.xmaxs = [np.max(nz[1]) + 1 if len(nz[1]) else im.shape[1] for nz, im in
                      zip(nzs, self.images)]  # +1 to allow easier indexing
        self.ymins = [np.min(nz[0]) if len(nz[0]) else 0 for nz in nzs]
        self.ymaxs = [np.max(nz[0]) + 1 if len(nz[0]) else im.shape[0] for nz, im in
                      zip(nzs, self.images)]  # +1 to allow easier indexing
        if self.crop_global:
            self.xmins = [np.min(self.xmins) for _ in self.xmins]
            self.xmaxs = [np.max(self.xmaxs) for _ in self.xmaxs]
            self.ymins = [np.min(self.ymins) for _ in self.ymins]
            self.ymaxs = [np.max(self.ymaxs) for _ in self.ymaxs]

    def initUI(self):
        #self.fig = plt.figure(figsize = (10, 10))
        #self.ax = plt.axes([0,0,1,1])#, self.gs[0])
        
        self.widget = QWidget()
        
        self.fig = Figure(dpi=100)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setParent(self.widget)
        
        #self.ax = Axes(fig=self.fig, rect=[0,0,1,1])
        self.ax = self.fig.add_subplot(111)
        self.ax.set_position(Bbox([[0, 0], [1, 1]]))
        self.ax.set_anchor('NW')
        try:
            self.ax.get_yaxis().set_inverted(True)
        except Exception:
            self.ax.invert_yaxis()

        self.uiLabelModifiers = QLabel('')
        self.uiLEScale = QLineEdit(str(self.scale))
        self.uiLEScale.setMinimumWidth(200)
        self.uiLEScale.editingFinished.connect(lambda: self.callbackLineEdit(self.uiLEScale))
        self.uiLEGamma = QLineEdit(str(self.gamma))
        self.uiLEGamma.setMinimumWidth(200)
        self.uiLEGamma.editingFinished.connect(lambda: self.callbackLineEdit(self.uiLEGamma))
        self.uiLEOffset = QLineEdit(str(self.offset))
        self.uiLEOffset.setMinimumWidth(200)
        self.uiLEOffset.editingFinished.connect(lambda: self.callbackLineEdit(self.uiLEOffset))
        self.uiLEAutoscalePrctile = QLineEdit(str(self.autoscalePrctile))
        self.uiLEAutoscalePrctile.setMinimumWidth(200)
        self.uiLEAutoscalePrctile.editingFinished.connect(lambda: self.callbackLineEdit(self.uiLEAutoscalePrctile))
        self.uiCBAutoscaleUsePrctiles = QCheckBox('use percentiles')
        self.uiCBAutoscaleUsePrctiles.setCheckState(self.autoscaleUsePrctiles)
        self.uiCBAutoscaleUsePrctiles.setTristate(False)
        self.uiCBAutoscaleUsePrctiles.stateChanged.connect(lambda state: self.callbackCheckBox(self.uiCBAutoscaleUsePrctiles, state))
        self.uiCBAutoscaleOnChange = QCheckBox('on change')
        self.uiCBAutoscaleOnChange.setCheckState(self.autoscaleOnChange)
        self.uiCBAutoscaleOnChange.setTristate(False)
        self.uiCBAutoscaleOnChange.stateChanged.connect(lambda state: self.callbackCheckBox(self.uiCBAutoscaleOnChange, state))
        if self.nims > 1:
            self.uiCBAutoscalePerImg = QCheckBox('per image')
            self.uiCBAutoscalePerImg.setCheckState(self.autoscalePerImg)
            self.uiCBAutoscalePerImg.setTristate(False)
            self.uiCBAutoscalePerImg.stateChanged.connect(lambda state: self.callbackCheckBox(self.uiCBAutoscalePerImg, state))
            self.uiCBCollageActive = QCheckBox('enable')
            self.uiCBCollageActive.setCheckState(self.collageActive)
            self.uiCBCollageActive.setTristate(False)
            self.uiCBCollageActive.stateChanged.connect(lambda state: self.callbackCheckBox(self.uiCBCollageActive, state))
            self.uiCBCollageTranspose = QCheckBox('transpose')
            self.uiCBCollageTranspose.setCheckState(self.collageTranspose)
            self.uiCBCollageTranspose.setTristate(False)
            self.uiCBCollageTranspose.stateChanged.connect(lambda state: self.callbackCheckBox(self.uiCBCollageTranspose, state))
            self.uiCBCollageTransposeIms = QCheckBox('transpose images')
            self.uiCBCollageTransposeIms.setCheckState(self.collageTransposeIms)
            self.uiCBCollageTransposeIms.setTristate(False)
            self.uiCBCollageTransposeIms.stateChanged.connect(lambda state: self.callbackCheckBox(self.uiCBCollageTransposeIms, state))
            self.uiLECollageNr = QLineEdit(str(self.collage_nr))
            self.uiLECollageNr.setMinimumWidth(200)
            self.uiLECollageNr.editingFinished.connect(lambda: self.callbackLineEdit(self.uiLECollageNr))
            self.uiLECollageNc = QLineEdit(str(self.collage_nc))
            self.uiLECollageNc.setMinimumWidth(200)
            self.uiLECollageNc.editingFinished.connect(lambda: self.callbackLineEdit(self.uiLECollageNc))
            self.uiLECollageBW = QLineEdit(str(self.collage_border_width))
            self.uiLECollageBW.setMinimumWidth(200)
            self.uiLECollageBW.editingFinished.connect(lambda: self.callbackLineEdit(self.uiLECollageBW))
            self.uiLECollageBV = QLineEdit(str(self.collage_border_value))
            self.uiLECollageBV.setMinimumWidth(200)
            self.uiLECollageBV.editingFinished.connect(lambda: self.callbackLineEdit(self.uiLECollageBV))
        self.uiCBCrop = QCheckBox('enable')
        self.uiCBCrop.setCheckState(self.crop)
        self.uiCBCrop.setTristate(False)
        self.uiCBCrop.stateChanged.connect(lambda state: self.callbackCheckBox(self.uiCBCrop, state))
        self.uiCBCropGlobal = QCheckBox('enable')
        self.uiCBCropGlobal.setCheckState(self.crop_global)
        self.uiCBCropGlobal.setTristate(False)
        self.uiCBCropGlobal.stateChanged.connect(lambda state: self.callbackCheckBox(self.uiCBCropGlobal, state))
        self.uiCBAnnotate = QCheckBox('enable')
        self.uiCBAnnotate.setCheckState(self.annotate)
        self.uiCBAnnotate.setTristate(False)
        self.uiCBAnnotate.stateChanged.connect(lambda state: self.callbackCheckBox(self.uiCBAnnotate, state))
        self.uiLEFontSize = QLineEdit(str(self.font_size))
        self.uiLEFontSize.setMinimumWidth(200)
        self.uiLEFontSize.editingFinished.connect(lambda: self.callbackLineEdit(self.uiLEFontSize))
        self.uiPBCopyClipboard = QPushButton('&copy')
        self.uiPBCopyClipboard.clicked.connect(lambda: self.callbackPushButton(self.uiPBCopyClipboard))
        
        form = QFormLayout()
        form.addRow(QLabel('modifiers:'), self.uiLabelModifiers)
        form.addRow(QLabel('scale:'), self.uiLEScale)
        form.addRow(QLabel('gamma:'), self.uiLEGamma)
        form.addRow(QLabel('offset:'), self.uiLEOffset)
        form.addRow(QLabel('autoScale:'), self.uiCBAutoscaleUsePrctiles)
        form.addRow(QLabel('percentile:'), self.uiLEAutoscalePrctile)
        form.addRow(QLabel('autoScale:'), self.uiCBAutoscaleOnChange)
        if self.nims > 1:
            form.addRow(QLabel('autoScale:'), self.uiCBAutoscalePerImg)
            form.addRow(QLabel('collage:'), self.uiCBCollageActive)
            form.addRow(QLabel('collage:'), self.uiCBCollageTranspose)
            form.addRow(QLabel('collage:'), self.uiCBCollageTransposeIms)
            form.addRow(QLabel('collage #rows:'), self.uiLECollageNr)
            form.addRow(QLabel('collage #cols:'), self.uiLECollageNc)
            form.addRow(QLabel('collage #BW:'), self.uiLECollageBW)
            form.addRow(QLabel('collage #BV:'), self.uiLECollageBV)
        form.addRow(QLabel('crop:'), self.uiCBCrop)
        form.addRow(QLabel('crop global:'), self.uiCBCropGlobal)
        form.addRow(QLabel('annotate:'), self.uiCBAnnotate)
        form.addRow(QLabel('font size:'), self.uiLEFontSize)
        form_bottom = QFormLayout()
        form_bottom.addRow(self.uiPBCopyClipboard)
        vbox = QVBoxLayout()
        vbox.addLayout(form)
        vbox.addItem(QSpacerItem(1, 1, vPolicy=QSizePolicy.Expanding))
        vbox.addLayout(form_bottom)
        
        hbox = QHBoxLayout()
        hbox.addWidget(self.canvas)
        hbox.addLayout(vbox)
        
        self.widget.setLayout(hbox)
        self.setCentralWidget(self.widget)
        
        # make image canvas expand with window
        sp = self.canvas.sizePolicy()
        sp.setHorizontalStretch(1)
        sp.setVerticalStretch(1)
        self.canvas.setSizePolicy(sp)
        
        self.ih = self.ax.imshow(np.zeros(self.get_img().shape[:2] + (3,)), origin='upper')
        self.ax.set_position(Bbox([[0, 0], [1, 1]]))
        try:
            self.ax.get_yaxis().set_inverted(True)
        except Exception:
            self.ax.invert_yaxis()

        # keyboard shortcuts
        #scaleShortcut = QShortcut(QKeySequence('Ctrl+Shift+a'), self.widget)
        #scaleShortcut.activated.connect(self.autoscale)
        closeShortcut = QShortcut(QKeySequence('Escape'), self.widget)
        closeShortcut.activated.connect(self.close)
        QShortcut(QKeySequence('a'), self.widget).activated.connect(self.autoscale)
        QShortcut(QKeySequence('Shift+a'), self.widget).activated.connect(self.toggleautoscaleUsePrctiles)

    #@MyPyQtSlot("bool")
    def callbackLineEdit(self, ui):
        try:
            tmp = float(ui.text())
        except:
            return
        
        if ui == self.uiLEScale:
            self.setScale(tmp)
        elif ui == self.uiLEGamma:
            self.setGamma(tmp)
        elif ui == self.uiLEOffset:
            self.setOffset(tmp)
        elif ui == self.uiLEAutoscalePrctile:
            self.autoscalePrctile = tmp
            self.autoscale()
        elif ui == self.uiLECollageNr:
            self.collage_nr = int(tmp)
            self.collage()
        elif ui == self.uiLECollageNc:
            self.collage_nc = int(tmp)
            self.collage()
        elif ui == self.uiLECollageBW:
            self.collage_border_width = int(tmp)
            self.collage()
        elif ui == self.uiLECollageBV:
            self.collage_border_value = float(tmp)
            self.collage()
        elif ui == self.uiLEFontSize:
            self.font_size = int(tmp)
            self.updateImage()


    #@MyPyQtSlot("bool")
    def callbackCheckBox(self, ui, state):
        if ui == self.uiCBAutoscaleUsePrctiles:
            self.autoscaleUsePrctiles = bool(state)
            if self.autoscaleOnChange:
                self.autoscale()
        elif ui == self.uiCBAutoscaleOnChange:
            self.autoscaleOnChange = bool(state)
            if self.autoscaleOnChange:
                self.autoscale()
        elif ui == self.uiCBAutoscalePerImg:
            self.autoscalePerImg = bool(state)
            self.autoscale()
        elif ui == self.uiCBCollageActive:
            self.collageActive = bool(state)
            self.updateImage()
        elif ui == self.uiCBCollageTranspose:
            self.collageTranspose = bool(state)
            self.updateImage()
        elif ui == self.uiCBCollageTransposeIms:
            self.collageTransposeIms = bool(state)
            self.updateImage()
        elif ui == self.uiCBCrop:
            self.crop = bool(state)
            self.updateImage()
        elif ui == self.uiCBCropGlobal:
            self.crop_global = bool(state)
            self.crop_bounds()
            self.updateImage()
        elif ui == self.uiCBAnnotate:
            self.annotate = bool(state)
            self.updateImage()
            
    def callbackPushButton(self, ui):
        if ui == self.uiPBCopyClipboard:
            self.copy_to_clipboard()
    
    '''
    @MyPyQtSlot()
    def slot_text(self):#, ui=None):
        ui = self.uiLEScale
        if ui == self.uiLEScale:
            print('scale: ' + str(self.scale))
            tmp = self.scale
            try:
                tmp = float(self.uiLEScale.text())
            except ValueError:
                print('error')
                self.uiLEScale.setText(str(self.scale))
            self.scale = tmp
            self.updateImage()
        elif ui == self.uiLEGamma:
            print('gamma')
        elif ui == self.uiLEOffset:
            print('offset')
    
    def on_draw(self):
        """ Redraws the figure
        """
        #self.axes.grid(self.grid_cb.isChecked())
        self.canvas.draw()
    '''
    
    def print_usage(self):
        print(' ')
        print('hotkeys: ')
        print('a: trigger autoscale')
        print('A: toggle autoscale of [min, max] or ')
        print('   [prctile_low, prctile_high] -> [0, 1], ')
        print('   prctiles can be changed via ctrl+shift+wheel')
        print('c: toggle autoscale on image change')
        print('G: reset gamma to 1')
        print('L: create collage by arranging all images in a ')
        print('   rectangular manner')
        print('O: reset offset to 0')
        print('p: toggle per image auto scale limit computations ')
        print('   (vs. globally over all images)')
        print('S: reset scale to 1')
        print('Z: reset zoom to 100%')
        print('left / right:         switch to next / previous image')
        print('page down / up:       go through images in ~10% steps')
        print('')
        print('wheel:                zoom in / out (inside image axes)')
        print('wheel:                switch to next / previous image')
        print('                      (outside image axes)')
        print('ctrl + wheel:         scale up / down')
        print('shift + wheel:        gamma up / down')
        print('ctrl + shift + wheel: increase / decrease autoscale')
        print('                      percentiles')
        print('left mouse dragged:   pan image')
        print('')
    
    def get_img(self, i=None):
        if i is None:
            i = self.imind
        im = self.images[i]
        if self.crop:
            im = im[self.ymins[i] : self.ymaxs[i], self.xmins[i] : self.xmaxs[i], :]
        if self.annotate:
            from pytb.utils import annotate_image
            im = annotate_image(im, str(i), font_size=self.font_size)
        return im
    
    def get_imgs(self):
        return [self.get_img(ind) for ind in range(len(self.images))]
    
    def copy_to_clipboard(self):
        from PyQt5.Qt import QImage
        im = (255 * self.ih.get_array()).astype(np.uint8)
        h, w, nc = im.shape[:3]
        im = QImage(im.tobytes(), w, h, nc * w, QImage.Format_RGB888)
        c = QApplication.clipboard()
        c.setImage(im)
    
    def autoscale(self):
        # autoscale between user-selected percentiles
        if self.autoscaleUsePrctiles:
            if self.autoscalePerImg:
                lower, upper = np.percentile(self.get_img(), (self.autoscalePrctile, 100 - self.autoscalePrctile))
            else:
                limits = [np.percentile(image, (self.autoscalePrctile, 100 - self.autoscalePrctile)) for image in self.get_imgs()]
                lower = np.min([lims[0] for lims in limits])
                upper= np.max([lims[1] for lims in limits])
        else:
            if self.autoscalePerImg:
                lower = np.min(self.get_img())
                upper = np.max(self.get_img())
            else:
                lower = np.min([np.min(image) for image in self.get_imgs()])
                upper = np.max([np.max(image) for image in self.get_imgs()])
        self.setOffset(lower, False)
        self.setScale(1. / (upper - lower), True)

    def toggleautoscaleUsePrctiles(self):
        self.autoscaleUsePrctiles = not self.autoscaleUsePrctiles
        self.autoscale()

    def collage(self):
        if self.collage_nr * self.collage_nc < self.nims:
            nc = int(np.ceil(np.sqrt(self.nims)))
            nr = int(np.ceil(self.nims / nc))
            self.collage_nr = nr
            self.collage_nc = nc
            self.uiLECollageNr.blockSignals(True)
            self.uiLECollageNc.blockSignals(True)
            self.uiLECollageNr.setText(str(nr))
            self.uiLECollageNc.setText(str(nc))
            self.uiLECollageNr.blockSignals(False)
            self.uiLECollageNc.blockSignals(False)
        else:
            nc = self.collage_nc
            nr = self.collage_nr
        
        # pad array so it matches the product nc * nr
        padding = nc * nr - self.nims
        ims = self.get_imgs()
        h = np.max([im.shape[0] for im in ims])
        w = np.max([im.shape[1] for im in ims])
        numChans = np.max([im.shape[2] for im in ims])
        ims = [pad(im, new_width=w, new_height=h, new_num_channels=numChans) for im in ims]
        ims += [np.zeros((h, w, numChans))] * padding
        coll = np.stack(ims, axis=3)
        coll = np.reshape(coll, (h, w, numChans, nc, nr))
        # 0  1  2   3   4
        # y, x, ch, co, ro
        if self.collage_border_width:
            # pad each patch by border if requested
            coll = np.append(coll, self.collage_border_value * np.ones((self.collage_border_width, ) + coll.shape[1 : 5]), axis=0)
            coll = np.append(coll, self.collage_border_value * np.ones((coll.shape[0], self.collage_border_width) + coll.shape[2 : 5]), axis=1)
        if self.collageTranspose:
            nim0 = nr
            nim1 = nc
            if self.collageTransposeIms:
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
            if self.collageTransposeIms:
                dim0 = w
                dim1 = h
                #                          nc w  nr h  ch
                coll = np.transpose(coll, (3, 1, 4, 0, 2))
            else:
                dim0 = h
                dim1 = w
                #                          nc h  nr w  ch
                coll = np.transpose(coll, (3, 0, 4, 1, 2))
        coll = np.reshape(coll, ((dim0 + self.collage_border_width) * nim0, (dim1 + self.collage_border_width) * nim1, numChans))
        
        #self.ih.set_data(self.tonemap(coll))
        self.ax.clear()
        self.ih = self.ax.imshow(self.tonemap(coll), origin='upper')
        
        height, width = self.ih.get_size()
        lims = (-0.5, width - 0.5, -0.5, height - 0.5)
        self.ax.set(xlim = lims[0:2], ylim = lims[2:4])
        try:
            self.ax.get_yaxis().set_inverted(True)
        except Exception:
            self.ax.invert_yaxis()
        self.fig.canvas.draw()
    
    def switch_to_single_image(self):
        if self.collageActive:
            self.ax.clear()
            self.ih = self.ax.imshow(np.zeros(self.get_img().shape[:3]), origin='upper')
        self.collageActive = False
        
    def reset_zoom(self):
        height, width = self.ih.get_size()
        lims = (-0.5, width - 0.5, -0.5, height - 0.5)
        self.ih.axes.axis(lims)
        self.ax.set_position(Bbox([[0, 0], [1, 1]]))
        try:
            self.ax.get_yaxis().set_inverted(True)
        except Exception:
            self.ax.invert_yaxis()
        self.fig.canvas.draw()
        
    def zoom(self, pos, factor):
        lims = self.ih.axes.axis();
        xlim = lims[0 : 2]
        ylim = lims[2 : ]
        
        # compute interval lengths left, right, below and above cursor
        left = pos[0] - xlim[0]
        right = xlim[1] - pos[0]
        below = pos[1] - ylim[0]
        above = ylim[1] - pos[1]
        
        # zoom in or out
        if self.x_zoom:
            xlim = [pos[0] - factor * left, pos[0] + factor * right]
        if self.y_zoom:
            ylim = [pos[1] - factor * below, pos[1] + factor * above]
        
        # no zooming out beyond original zoom level
        height, width = self.ih.get_size()
        
        if self.x_stop_at_orig:
            xlim = [np.maximum(-0.5, xlim[0]), np.minimum(width - 0.5, xlim[1])]
        
        if self.y_stop_at_orig:
            ylim = [np.maximum(-0.5, ylim[0]), np.minimum(height - 0.5, ylim[1])]
        
        # update axes
        if xlim[0] != xlim[1] and ylim[0] != ylim[1]:
            lims = (xlim[0], xlim[1], ylim[0], ylim[1])
            self.ih.axes.axis(lims)
            try:
                self.ax.get_yaxis().set_inverted(True)
            except Exception:
                self.ax.invert_yaxis()
            self.ax.set_position(Bbox([[0, 0], [1, 1]]))
            self.fig.canvas.draw()
        return
        
    def tonemap(self, im):
        if isinstance(im, np.matrix):
            im = np.array(im)
        if im.shape[2] == 1:
            im = np.repeat(im, 3, axis=2)
        elif im.shape[2] == 2:
            im = np.concatenate((im, np.zeros((im.shape[0], im.shape[1], 2), dtype=im.dtype)), axis=2)
        elif im.shape[2] != 3:
            # project to RGB
            raise Exception('spectral to RGB conversion not implemented')
        return np.power(np.maximum(0., np.minimum(1., (im - self.offset) * self.scale)), 1. / self.gamma)
        
    def updateImage(self):
        if self.collageActive:
            self.collage()
        else:
            if self.nims > 1:
                self.uiCBCollageActive.blockSignals(True)
                self.uiCBCollageActive.setChecked(False)
                self.uiCBCollageActive.blockSignals(False)
            height, width = self.ih.get_size()
            im = self.get_img()
            if height != im.shape[0] or width != im.shape[1]:
                # image size changed, create new axes
                self.ax.clear()
                self.ih = self.ax.imshow(self.tonemap(im))
            else:
                self.ih.set_data(self.tonemap(im))
            height, width = self.ih.get_size()
            lims = (-0.5, width - 0.5, -0.5, height - 0.5)
            self.ax.set(xlim = lims[0:2], ylim = lims[2:4])
            try:
                self.ax.get_yaxis().set_inverted(True)
            except Exception:
                self.ax.invert_yaxis()
            self.fig.canvas.draw()
    
    def setScale(self, scale, update=True):
        self.scale = scale
        self.uiLEScale.setText(str(self.scale))
        if update:
            self.updateImage()
    
    def setGamma(self, gamma, update=True):
        self.gamma = gamma
        self.uiLEGamma.setText(str(self.gamma))
        if update:
            self.updateImage()
    
    def setOffset(self, offset, update=True):
        self.offset = offset
        self.uiLEOffset.setText(str(self.offset))
        if update:
            self.updateImage()
    
    def onclick(self, event):
        if event.dblclick:
            self.reset_zoom()
            self.mouse_down ^= event.button
        elif event.inaxes:
            self.x_start = event.xdata
            self.y_start = event.ydata
            self.prev_delta_x = 0
            self.prev_delta_y = 0
            self.cur_xlims = self.ih.axes.axis()[0 : 2]
            self.cur_ylims = self.ih.axes.axis()[2 :]
            self.mouse_down |= event.button
            
    def onrelease(self, event):
        self.mouse_down ^= event.button
            
    def onmotion(self, event):
        if self.mouse_down == 1 and event.inaxes:
            delta_x = self.x_start - event.xdata
            delta_y = self.y_start - event.ydata
            self.ih.axes.axis((self.cur_xlims[0] + delta_x,
                               self.cur_xlims[1] + delta_x, 
                               self.cur_ylims[0] + delta_y,
                               self.cur_ylims[1] + delta_y))
            self.fig.canvas.draw()
            self.x_start += (delta_x - self.prev_delta_x)
            self.y_start += (delta_y - self.prev_delta_y)
            self.prev_delta_x = delta_x
            self.prev_delta_y = delta_y
    
    def keyPressEvent(self, event):
    #def onkeypress(self, event):
        key = event.key()
        mod = event.modifiers()
        if key == Qt.Key_Question: # ?
            self.print_usage()
        elif key == Qt.Key_A: # a
            # trigger autoscale
            self.autoscale()
            return
        elif key == Qt.Key_A and mod == Qt.Key_Shift: # A
            # toggle autoscale between user-selected percentiles or min-max
            self.autoscaleUsePrctiles = not self.autoscaleUsePrctiles
            self.autoscale()
            return
        elif key == Qt.Key_C:
            # toggle on-change autoscale
            self.autoscaleOnChange = not self.autoscaleOnChange
            print('on-change autoscaling is %s' % ('on' if self.autoscaleOnChange else 'off'))
        elif key == Qt.Key_G:
            self.gamma = 1.
        elif key == Qt.Key_L:
            # update axes for single image dimensions
            if self.collageActive:
                self.switch_to_single_image()
            else:
                # toggle showing collage
                self.collageActive = not self.collageActive
            # also disable per-image scaling limit computation
            self.autoscalePerImg = not self.autoscalePerImg
        elif key == Qt.Key_O:
            self.offset = 0.
        elif key == Qt.Key_P:
            self.autoscalePerImg = not self.autoscalePerImg
            print('per-image scaling is %s' % ('on' if self.autoscalePerImg else 'off'))
            self.autoscale()
        elif key == Qt.Key_S:
            self.scale = 1.
        elif key == Qt.Key_Z:
            # reset zoom
            self.ih.axes.autoscale(True)
        elif key == Qt.Key_Alt:
            self.alt = True
            self.uiLabelModifiers.setText('alt: %d, ctrl: %d, shift: %d' % (self.alt, self.control, self.shift))
            return
        elif key == Qt.Key_Control:
            self.control = True
            self.uiLabelModifiers.setText('alt: %d, ctrl: %d, shift: %d' % (self.alt, self.control, self.shift))
            return
        elif key == Qt.Key_Shift:
            self.shift = True
            self.uiLabelModifiers.setText('alt: %d, ctrl: %d, shift: %d' % (self.alt, self.control, self.shift))
            return
        elif key == Qt.Key_Left:
            self.switch_to_single_image()
            self.imind = np.mod(self.imind - 1, self.nims)
            print('image %d / %d' % (self.imind + 1, self.nims))
            if self.autoscaleOnChange:
                self.autoscale()
                return
        elif key == Qt.Key_Right:
            self.switch_to_single_image()
            self.imind = np.mod(self.imind + 1, self.nims)
            print('image %d / %d' % (self.imind + 1, self.nims))
            if self.autoscaleOnChange:
                self.autoscale()
                return
        else:
            return
        self.updateImage()
            
    def keyReleaseEvent(self, event):
    #def onkeyrelease(self, event):
        key = event.key()
        if key == Qt.Key_Alt:
            self.alt = False
        elif key == Qt.Key_Control:
            self.control = False
        elif key == Qt.Key_Shift:
            self.shift = False
        self.uiLabelModifiers.setText('alt: %d, ctrl: %d, shift: %d' % (self.alt, self.control, self.shift))
    
    def onscroll(self, event):
        if self.control and self.shift:
            # autoscale percentiles
            self.autoscalePrctile *= np.power(1.1, event.step)
            self.autoscalePrctile = np.minimum(100, self.autoscalePrctile)
            print('auto percentiles: [%3.5f, %3.5f]' % (self.autoscalePrctile, 100 - self.autoscalePrctile))
            self.autoscaleUsePrctiles = True
            self.autoscale()
        elif self.control:
            # scale
            #self.setScale(self.scale * np.power(1.1, event.step))
            self.setScale(self.scale * np.power(1.1, event.step))
        elif self.shift:
            # gamma
            self.setGamma(self.gamma * np.power(1.1, event.step))
        elif event.inaxes:
            # zoom when inside image axes
            factor = np.power(self.zoom_factor, -event.step)
            self.zoom([event.xdata, event.ydata], factor)
            return
        else:
            # scroll through images when outside of axes
            self.switch_to_single_image()
            self.imind = int(np.mod(self.imind - event.step, self.nims))
            print('image %d / %d' % (self.imind + 1, self.nims))
            if self.autoscaleOnChange:
                self.autoscale()
                return
        self.updateImage()
    
    def save(self, ofname):
        imageio.imwrite(ofname, np.array(self.ih.get_array()))