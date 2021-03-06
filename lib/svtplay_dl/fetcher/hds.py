# ex:ts=4:sw=4:sts=4:et
# -*- tab-width: 4; c-basic-offset: 4; indent-tabs-mode: nil -*-
from __future__ import absolute_import
import sys
import base64
import re
import struct
import logging
import binascii
import os
import xml.etree.ElementTree as ET

from svtplay_dl.output import progressbar, progress_stream, ETA
from svtplay_dl.utils import get_http_data, is_py2_old, is_py2, is_py3
from svtplay_dl.utils.urllib import urlparse
from svtplay_dl.error import UIException
from svtplay_dl.fetcher import VideoRetriever

log = logging.getLogger('svtplay_dl')

if is_py2:
    def bytes(string=None, encoding="ascii"):
        if string is None:
            return ""
        return string

    def _chr(temp):
        return temp

if is_py3:
    def _chr(temp):
        return chr(temp)

class HDSException(UIException):
    def __init__(self, url, message):
        self.url = url
        super(HDSException, self).__init__(message)


class LiveHDSException(HDSException):
    def __init__(self, url):
        super(LiveHDSException, self).__init__(
            url, "This is a live HDS stream, and they are not supported.")

def hdsparse(options, manifest):
    data = get_http_data(manifest)
    streams = {}
    bootstrap = {}
    xml = ET.XML(data)

    if is_py2_old:
        bootstrapIter = xml.getiterator("{http://ns.adobe.com/f4m/1.0}bootstrapInfo")
        mediaIter = xml.getiterator("{http://ns.adobe.com/f4m/1.0}media")
    else:
        bootstrapIter = xml.iter("{http://ns.adobe.com/f4m/1.0}bootstrapInfo")
        mediaIter = xml.iter("{http://ns.adobe.com/f4m/1.0}media")

    for i in bootstrapIter:
        bootstrap[i.attrib["id"]] = i.text
    parse = urlparse(manifest)
    querystring = parse.query
    for i in mediaIter:
        streams[int(i.attrib["bitrate"])] = HDS(options, i.attrib["url"], i.attrib["bitrate"], manifest=manifest, bootstrap=bootstrap[i.attrib["bootstrapInfoId"]], metadata=i.find("{http://ns.adobe.com/f4m/1.0}metadata").text, querystring=querystring)
    return streams

class HDS(VideoRetriever):
    def name(self):
        return "hds"

    def download(self):
        if self.options.live and not self.options.force:
            raise LiveHDSException(self.url)

        querystring = self.kwargs["querystring"]
        bootstrap = base64.b64decode(self.kwargs["bootstrap"])
        box = readboxtype(bootstrap, 0)
        antal = None
        if box[2] == b"abst":
            antal = readbox(bootstrap, box[0])
        baseurl = self.kwargs["manifest"][0:self.kwargs["manifest"].rfind("/")]

        if self.options.output != "-":
            extension = re.search(r"(\.[a-z0-9]+)$", self.options.output)
            if not extension:
                self.options.output = "%s.flv" % self.options.output
            log.info("Outfile: %s", self.options.output)
            if os.path.isfile(self.options.output) and not self.options.force:
                log.info("File already exists. use --force to overwrite")
                return
            file_d = open(self.options.output, "wb")
        else:
            file_d = sys.stdout

        metasize = struct.pack(">L", len(base64.b64decode(self.kwargs["metadata"])))[1:]
        file_d.write(binascii.a2b_hex(b"464c560105000000090000000012"))
        file_d.write(metasize)
        file_d.write(binascii.a2b_hex(b"00000000000000"))
        file_d.write(base64.b64decode(self.kwargs["metadata"]))
        file_d.write(binascii.a2b_hex(b"00000000"))
        i = 1
        start = antal[1]["first"]
        total = antal[1]["total"]
        eta = ETA(total)
        while i <= total:
            url = "%s/%sSeg1-Frag%s?%s" % (baseurl, self.url, start, querystring)
            if self.options.output != "-":
                eta.update(i)
                progressbar(total, i, ''.join(["ETA: ", str(eta)]))
            data = get_http_data(url)
            number = decode_f4f(i, data)
            file_d.write(data[number:])
            i += 1
            start += 1

        if self.options.output != "-":
            file_d.close()
            progress_stream.write('\n')

def readbyte(data, pos):
    return struct.unpack("B", bytes(_chr(data[pos]), "ascii"))[0]

def read16(data, pos):
    endpos = pos + 2
    return struct.unpack(">H", data[pos:endpos])[0]

def read24(data, pos):
    end = pos + 3
    return struct.unpack(">L", "\x00" + data[pos:end])[0]

def read32(data, pos):
    end = pos + 4
    return struct.unpack(">i", data[pos:end])[0]

def readu32(data, pos):
    end = pos + 4
    return struct.unpack(">I", data[pos:end])[0]

def read64(data, pos):
    end = pos + 8
    return struct.unpack(">Q", data[pos:end])[0]

def readstring(data, pos):
    length = 0
    while bytes(_chr(data[pos + length]), "ascii") != b"\x00":
        length += 1
    endpos = pos + length
    string = data[pos:endpos]
    pos += length + 1
    return pos, string

def readboxtype(data, pos):
    boxsize = read32(data, pos)
    tpos = pos + 4
    endpos = tpos + 4
    boxtype = data[tpos:endpos]
    if boxsize > 1:
        boxsize -= 8
        pos += 8
        return pos, boxsize, boxtype

# Note! A lot of variable assignments are commented out. These are
# accessible values that we currently don't use.
def readbox(data, pos):
    #version = readbyte(data, pos)
    pos += 1
    #flags = read24(data, pos)
    pos += 3
    #bootstrapversion = read32(data, pos)
    pos += 4
    #byte = readbyte(data, pos)
    pos += 1
    #profile = (byte & 0xC0) >> 6
    #live = (byte & 0x20) >> 5
    #update = (byte & 0x10) >> 4
    #timescale = read32(data, pos)
    pos += 4
    #currentmediatime = read64(data, pos)
    pos += 8
    #smptetimecodeoffset = read64(data, pos)
    pos += 8
    temp = readstring(data, pos)
    #movieidentifier = temp[1]
    pos = temp[0]
    serverentrycount = readbyte(data, pos)
    pos += 1
    serverentrytable = []
    i = 0
    while i < serverentrycount:
        temp = readstring(data, pos)
        serverentrytable.append(temp[1])
        pos = temp[0]
        i += 1
    qualityentrycount = readbyte(data, pos)
    pos += 1
    qualityentrytable = []
    i = 0
    while i < qualityentrycount:
        temp = readstring(data, pos)
        qualityentrytable.append(temp[1])
        pos = temp[0]
        i += 1

    tmp = readstring(data, pos)
    #drm = tmp[1]
    pos = tmp[0]
    tmp = readstring(data, pos)
    #metadata = tmp[1]
    pos = tmp[0]
    segmentruntable = readbyte(data, pos)
    pos += 1
    if segmentruntable > 0:
        tmp = readboxtype(data, pos)
        boxtype = tmp[2]
        boxsize = tmp[1]
        pos = tmp[0]
        if boxtype == b"asrt":
            antal = readasrtbox(data, pos)
            pos += boxsize
    fragRunTableCount = readbyte(data, pos)
    pos += 1
    i = 0
    first = 1
    while i < fragRunTableCount:
        tmp = readboxtype(data, pos)
        boxtype = tmp[2]
        boxsize = tmp[1]
        pos = tmp[0]
        if boxtype == b"afrt":
            first = readafrtbox(data, pos)
            pos += boxsize
        i += 1
    antal[1]["first"] = first
    return antal

# Note! A lot of variable assignments are commented out. These are
# accessible values that we currently don't use.
def readafrtbox(data, pos):
    #version = readbyte(data, pos)
    pos += 1
    #flags = read24(data, pos)
    pos += 3
    #timescale = read32(data, pos)
    pos += 4
    qualityentry = readbyte(data, pos)
    pos += 1
    i = 0
    while i < qualityentry:
        temp = readstring(data, pos)
        #qualitysegmulti = temp[1]
        pos = temp[0]
        i += 1
    fragrunentrycount = read32(data, pos)
    pos += 4
    i = 0
    first = 1
    skip = False
    while i < fragrunentrycount:
        firstfragment = readu32(data, pos)
        if not skip:
            first = firstfragment
            skip = True
        pos += 4
        #timestamp = read64(data, pos)
        pos += 8
        #duration = read32(data, pos)
        pos += 4
        i += 1
    return first

# Note! A lot of variable assignments are commented out. These are
# accessible values that we currently don't use.
def readasrtbox(data, pos):
    #version = readbyte(data, pos)
    pos += 1
    #flags = read24(data, pos)
    pos += 3
    qualityentrycount = readbyte(data, pos)
    pos += 1
    qualitysegmentmodifers = []
    i = 0
    while i < qualityentrycount:
        temp = readstring(data, pos)
        qualitysegmentmodifers.append(temp[1])
        pos = temp[0]
        i += 1

    seqCount = read32(data, pos)
    pos += 4
    ret = {}
    i = 0

    while i < seqCount:
        firstseg = read32(data, pos)
        pos += 4
        fragPerSeg = read32(data, pos)
        pos += 4
        tmp = i + 1
        ret[tmp] = {"first": firstseg, "total": fragPerSeg}
        i += 1
    return ret

def decode_f4f(fragID, fragData):
    start = fragData.find(b"mdat") + 4
    if (fragID > 1):
        tagLen, = struct.unpack_from(">L", fragData, start)
        tagLen &= 0x00ffffff
        start  += tagLen + 11 + 4
    return start

