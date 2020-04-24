# ==============================================================================
# MIT License
#
# Written by S. Kartik, VAST Data Ltd. April 2020
#
# Copyright (c) 2020 VAST Data Ltd.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# ==============================================================================

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
import os.path
from subprocess import call
from optparse import OptionParser
import tensorflow as tf

parser = OptionParser()
parser.add_option("-m", "--mode", dest="mode",
                  help="set cpu or gpu mode for NVIDIA DALI", metavar="MODE")
parser.add_option("-q", "--quiet",
                  action="store_false", dest="verbose", default=True,
                  help="don't print status messages to stdout")

(options, args) = parser.parse_args()
print("Argument, Processing mode:", args[0],options.mode)

import sys
print('Input TFRecord file:',args[0])
infile=args[0]
outfile='aug_'+infile

test_data_root = os.environ['DALI_EXTRA_PATH']
tfrecord = os.path.join(test_data_root,"imagenet-mini",infile)
print('About to count records...:',tfrecord)

count=0
for record in tf.io.tf_record_iterator(tfrecord):
    count+=1
print('Number of records:',count)

tfrecord_idx = "idx_files_"+infile+"/train.idx"
tfrecord2idx_script = "tfrecord2idx"

idx_dir='idx_files_'+infile
if not os.path.exists(idx_dir):
    os.mkdir(idx_dir)

if not os.path.isfile(tfrecord_idx):
    call([tfrecord2idx_script, tfrecord, tfrecord_idx])

# ==============================================================================
#
# NVIDIA DALI Pipeline Class definition. Adapted from NVIDIA DALI Documentation
# https://docs.nvidia.com/deeplearning/sdk/dali-developer-guide/docs/examples/general/data_loading/dataloading_tfrecord.html
#
# Code from Nvidia and 
# some class methods from James Dellinger's blog: 
# https://towardsdatascience.com/diving-into-dali-1c30c28731c0 
# and GitHub https://gist.github.com/jamesdellinger/c4a7aa588f2971a89c01484bb680c4e5
#
# ==============================================================================

from nvidia.dali.pipeline import Pipeline
import nvidia.dali.ops as ops
import nvidia.dali.types as types
import nvidia.dali.tfrecord as tfrec
import numpy as np
import matplotlib.pyplot as plt


class TFRecordPipeline(Pipeline):
    def __init__(self, batch_size, num_threads, device_id):
        super(TFRecordPipeline, self).__init__(batch_size,
                                         num_threads,
                                         device_id)
        self.input = ops.TFRecordReader(path = tfrecord,
                                        index_path = tfrecord_idx,
                                        features = {"image/encoded" : tfrec.FixedLenFeature((), tfrec.string, ""),
                                         'image/filename':            tfrec.FixedLenFeature([ ], tfrec.string, ''),
                                         'image/height':              tfrec.FixedLenFeature([1], tfrec.int64,  -1),
                                         'image/width':               tfrec.FixedLenFeature([1], tfrec.int64,  -1),
                                         'image/colorspace':          tfrec.FixedLenFeature([ ], tfrec.string, ''),
                                         'image/channels':            tfrec.FixedLenFeature([1], tfrec.int64,  -1),
                                         'image/format':              tfrec.FixedLenFeature([ ], tfrec.string, ''),
                                         'image/class/label':         tfrec.FixedLenFeature([1], tfrec.int64,  -1),
                                         'image/class/synset':        tfrec.FixedLenFeature([ ], tfrec.string, ''),
                                         'image/class/text':          tfrec.FixedLenFeature([ ], tfrec.string, ''),
                                         'image/object/bbox/xmin':    tfrec.VarLenFeature(tfrec.float32, 0.0),
                                         'image/object/bbox/ymin':    tfrec.VarLenFeature(tfrec.float32, 0.0),
                                         'image/object/bbox/xmax':    tfrec.VarLenFeature(tfrec.float32, 0.0),
                                         'image/object/bbox/ymax':    tfrec.VarLenFeature(tfrec.float32, 0.0),
                                         'image/object/bbox/label':   tfrec.FixedLenFeature([1], tfrec.int64, -1)})

        self.decode = ops.ImageDecoder(device = "mixed", output_type = types.RGB)
        self.resize = ops.Resize(device = "gpu", resize_x = 512.,resize_y=512.)
        self.vert_flip = ops.Flip(device = "gpu", horizontal=0)
        self.vert_coin = ops.CoinFlip(probability=0.5)
        self.rotate = ops.Rotate(device='gpu', interp_type=types.INTERP_NN)
        self.rotate_range = ops.Uniform(range = (-7, 7))
        self.rotate_coin = ops.CoinFlip(probability=0.2)
        self.cmnp = ops.CropMirrorNormalize(device = "gpu",
                                            output_dtype = types.FLOAT,
                                            crop = (512, 512),
                                            image_type = types.RGB,
                                            mean = [0., 0., 0.],
                                            std = [1., 1., 1.])
        self.mirror_coin  = ops.CoinFlip(probability=0.5)
        self.uniform = ops.Uniform(range = (0.0, 1.0))
        self.iter = 0

    def define_graph(self):
        prob_vert_flip=self.vert_coin()
        prob_rotate = self.rotate_coin()
        prob_mirror = self.mirror_coin()
        angle_range = self.rotate_range()

        inputs = self.input()
        images = self.decode(inputs["image/encoded"])
        resized_images = self.resize(images)
        resized_images=self.vert_flip(resized_images,vertical=prob_vert_flip)
        resized_images=self.rotate(resized_images, angle=angle_range)
        output = self.cmnp(resized_images, crop_pos_x = self.uniform(),
                           crop_pos_y = self.uniform(),mirror=prob_mirror)

        filename  =inputs["image/filename"]
        height    =inputs["image/height"]
        width     =inputs["image/width"]
        colorspace=inputs["image/colorspace"]
        channel   =inputs["image/channels"]
        iformat   =inputs["image/format"]
        label     =inputs["image/class/label"]
        synset    =inputs["image/class/synset"]
        text      =inputs["image/class/text"]
        xmin      =inputs["image/object/bbox/xmin"]
        ymin      =inputs["image/object/bbox/ymin"]
        xmax      =inputs["image/object/bbox/xmax"]
        ymax      =inputs["image/object/bbox/ymax"]
        bblabel   =inputs["image/object/bbox/label"]
        return (output,filename,height,width,colorspace,channel,
                iformat,label,synset,text,xmin,ymin,xmax,ymax,bblabel) 

    def iter_setup(self):
        pass

# End of TFRecordPipeline Class definition 
# ==============================================================================
#
# _convert_to_example and the ImageCoder class are subject to the license below
#
# _convert_to_example takes inputs and builds a TFRecord
#
# Copyright 2016 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

from datetime import datetime

import random
import sys
import threading

import six


def _int64_feature(value):
  """Wrapper for inserting int64 features into Example proto."""
  if not isinstance(value, list):
    value = [value]
  return tf.train.Feature(int64_list=tf.train.Int64List(value=value))


def _float_feature(value):
  """Wrapper for inserting float features into Example proto."""
  if not isinstance(value, list):
    value = [value]
  return tf.train.Feature(float_list=tf.train.FloatList(value=value))


def _bytes_feature(value):
  """Wrapper for inserting bytes features into Example proto."""
  if six.PY3 and isinstance(value, six.text_type):
    value = six.binary_type(value, encoding='utf-8')
  return tf.train.Feature(bytes_list=tf.train.BytesList(value=[value]))


def _convert_to_example(filename, image_buffer, label, synset, human, bbox,
                        height, width):
  """Build an Example proto for an example.

  Args:
    filename: string, path to an image file, e.g., '/path/to/example.JPG'
    image_buffer: string, JPEG encoding of RGB image
    label: integer, identifier for the ground truth for the network
    synset: string, unique WordNet ID specifying the label, e.g., 'n02323233'
    human: string, human-readable label, e.g., 'red fox, Vulpes vulpes'
    bbox: list of bounding boxes; each box is a list of integers
      specifying [xmin, ymin, xmax, ymax]. All boxes are assumed to belong to
      the same label as the image label.
    height: integer, image height in pixels
    width: integer, image width in pixels
  Returns:
    Example proto
  """
  xmin = []
  ymin = []
  xmax = []
  ymax = []
  for b in bbox:
    assert len(b) == 4
    # pylint: disable=expression-not-assigned
    [l.append(point) for l, point in zip([xmin, ymin, xmax, ymax], b)]
    # pylint: enable=expression-not-assigned

  colorspace = 'RGB'
  channels = 3
  image_format = 'JPEG'

  example = tf.train.Example(features=tf.train.Features(feature={
      'image/height': _int64_feature(height),
      'image/width': _int64_feature(width),
      'image/colorspace': _bytes_feature(colorspace),
      'image/channels': _int64_feature(channels),
      'image/class/label': _int64_feature(label),
      'image/class/synset': _bytes_feature(synset),
      'image/class/text': _bytes_feature(human),
      'image/object/bbox/xmin': _float_feature(xmin),
      'image/object/bbox/xmax': _float_feature(xmax),
      'image/object/bbox/ymin': _float_feature(ymin),
      'image/object/bbox/ymax': _float_feature(ymax),
      'image/object/bbox/label': _int64_feature([label] * len(xmin)),
      'image/format': _bytes_feature(image_format),
      'image/filename': _bytes_feature(os.path.basename(filename)),
      'image/encoded': _bytes_feature(image_buffer)}))
  return example


# End of _convert_to_example TFRecord
#
# ==============================================================================
# ImageCoder Class definition
#


class ImageCoder(object):
  """Helper class that provides TensorFlow image coding utilities."""

  def __init__(self):
    # Create a single Session to run all image coding calls.
    self._sess = tf.Session()

    # Initializes function that encodes JPEG
    self._image = tf.placeholder(dtype=tf.uint8)
    self._encode_jpeg = tf.image.encode_jpeg(self._image, format='rgb', quality=100,chroma_downsampling=False)

  def encode_jpeg(self, image):
    return self._sess.run(self._encode_jpeg,
                          feed_dict={self._image: image})

# End of ImageCoder Class definition
#
# ==============================================================================
#
# Main execution definition to read a TFRecord and iterate over it in batches
#

batch_size=8
pipe=TFRecordPipeline(batch_size=batch_size,num_threads=2,device_id=0)
pipe.build()

iteration=0
done=0

tfrecoutfile=test_data_root+"/imagenet-aug/"+outfile

writer=tf.io.TFRecordWriter(tfrecoutfile)

coder=ImageCoder()

while True:
    iteration=iteration+1
    
    pipe_out=pipe.run()

    images,filenames,heights,widths,colorspaces,channels,iformats,labels,synsets,texts,xmins,ymins,xmaxs,ymaxs,bblabels = pipe_out

    image_batch=images.as_cpu()
    image_tensor=images.as_tensor()
    print('image_tensor shape:', image_tensor.shape(),'iteration:',iteration)

    for img_index in range(batch_size):
        bbox=[]
        img_chw=image_batch.at(img_index)
        img_hwc=np.transpose(img_chw,(1,2,0))/255.
        ascii=filenames.at(img_index)
        fname="".join([chr(item) for item in ascii])
        height=img_hwc.shape[0]
        width =img_hwc.shape[1]
        label=labels.at(img_index)
        alabel="".join([chr(item) for item in label])
        ascii=synsets.at(img_index)
        synset="".join([chr(item) for item in ascii])
        ascii=texts.at(img_index)
        text="".join([chr(item) for item in ascii])
        if len(xmins.at(img_index)) == 0:
            xmin=ymin=xmax=ymax=0
            box=[xmin,ymin,xmax,ymax]
            bbox.append(box)
        else:
            for nb in range(0,len(xmins.at(img_index))):
                xmin=xmins.at(img_index)[nb]
                ymin=ymins.at(img_index)[nb]
                xmax=xmaxs.at(img_index)[nb]
                ymax=ymaxs.at(img_index)[nb]
                box=[xmin,ymin,xmax,ymax]
                bbox.append(box)
        bblabel=bblabels.at(img_index)
        fname=test_data_root+'/db/tfrecord/train/images-create/'+fname
        img=np.uint8(img_hwc*255.)
        enc_img=coder.encode_jpeg(img)
        otfrec=_convert_to_example(fname,enc_img,label,synset,text,bbox,height,width)
        writer.write(otfrec.SerializeToString())
        nimage=batch_size*(iteration-1)+img_index
        if nimage == count: 
            done=1
            break

    if done == 1: break    
writer.close()

print('Pipeline completed',infile)
