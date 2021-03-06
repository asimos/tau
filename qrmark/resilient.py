import numpy
import math
from pywt import dwt2, idwt2
from scipy.fftpack import fft2, ifft2, fftshift, ifftshift, dct, idct
from scipy.stats import pearsonr
from scipy import mean, median, misc
from skimage.filter import canny, sobel, threshold_otsu
from skimage.transform import probabilistic_hough
from PIL import Image
from random import Random
from reedsolo import RSCodec, ReedSolomonError


def distance(vec):
    dx, dy = vec
    return numpy.sqrt(dx*dx + dy*dy)

def line_to_vector(l):
    (x1, y1), (x2, y2) = l
    return x2 - x1, y2 - y1

def align(img, min_line_length = 100):
    sob = sobel(img)
    #print "!! sob"
    bw = sob > threshold_otsu(sob)
    #print "!! otsu"
    lines = probabilistic_hough(bw, line_length = min_line_length)
    #print "!! hough"
    sorted_lines = sorted(lines, key = lambda l: distance(line_to_vector(l)), 
        reverse = True)[:10]
    
    rotations = {}
    for l1 in sorted_lines:
        v1 = line_to_vector(l1)
        for l2 in sorted_lines:
            if l1 == l2:
                continue
            v2 = line_to_vector(l2)
            theta = numpy.arccos(numpy.dot(v1, v2) / (distance(v1) * distance(v2)))
            if abs(numpy.degrees(theta) - 90) <= 1:
                # found an alignment!
                angle = int(round(numpy.degrees(numpy.arccos(numpy.dot(v1, (0, 1)) / distance(v1)))))
                if angle > 90:
                    angle = -(angle % 90)
                if angle > 45:
                    angle = 90 - angle
                elif angle < -45:
                    angle = -90 - angle
                if angle not in rotations:
                    rotations[angle] = 0
                rotations[angle] += 1
    
    if not rotations:
        # couldn't find boundaries, assume aligned 
        return img
    
    angle = max(rotations.items(), key = lambda item: item[1])[0]
    img2 = misc.imrotate(img, angle)
    
    sob = sobel(img2)
    bw = sob > threshold_otsu(sob)
    lines = probabilistic_hough(bw, line_length = min_line_length)
    sorted_lines = sorted(lines, key = lambda l: distance(line_to_vector(l)), 
        reverse = True)[:4]
    
    min_y = bw.shape[0]
    max_y = 0
    min_x = bw.shape[1]
    max_x = 0
    
    for l in sorted_lines:
        (x1, y1), (x2, y2) = l
        if x1 < min_x:
            min_x = x1
        if x1 > max_x:
            max_x = x1
        if x2 < min_x:
            min_x = x2
        if x2 > max_x:
            max_x = x2
        if y1 < min_y:
            min_y = y1
        if y1 > max_y:
            max_y = y1
        if y2 < min_y:
            min_y = y2
        if y2 > max_y:
            max_y = y2
    
    img3 = img2[min_y+1:max_y, min_x+1:max_x]
    #return misc.imresize(img3, (512, 512))
    return img3

def expand_rotate(img, angle):
    expanded = numpy.zeros((img.shape[0] * 2, img.shape[1] * 2), img.dtype)
    expanded[img.shape[0] / 2:img.shape[0] / 2 + img.shape[0], img.shape[1] / 2: img.shape[1] / 2 + img.shape[1]] = img
    return misc.imrotate(expanded, angle)


def iterbits(data):  # MSB first
    if isinstance(data, str):
        data = (ord(ch) for ch in data)
    for n in data:
        for i in (7,6,5,4,3,2,1,0):
            yield (n >> i) & 1

def grayscale(img):
    if len(img.shape) == 2:
        return img
    else:
        return mean(img, 2)
        #return img[:,:,1]


class Watermarker(object):
    def __init__(self, msg_bytes, ec_bytes, seed, mother = "haar"):
        self.mother = mother
        self.rscodec = RSCodec(ec_bytes)
        self.msg_bytes = msg_bytes
        self.total_bits = (msg_bytes + ec_bytes) * 8

        rand = Random(seed)
        #self.mask = [rand.randint(0,255) for _ in range(msg_bytes + ec_bytes)]
        self.mask = [0] * (msg_bytes + ec_bytes)
        chunk_size = 256*512 // self.total_bits
        espilon = 0.0001
        while True:
            self.seq0 = numpy.array([int(rand.random() > 0.75) for _ in range(chunk_size)])
            self.seq1 = numpy.array([int(rand.random() > 0.7) for _ in range(chunk_size)])
            corr, _ = pearsonr(self.seq0, self.seq1)
            if abs(corr) < espilon:
                break
    
    def _embed(self, img, payload, k):
        cA, (cH, cV, cD) = dwt2(img, self.mother)
        w, h = cH.shape
        cH2 = cH.reshape(cH.size)
        cV2 = cV.reshape(cV.size)
        chunk_size = cH2.size // (self.total_bits // 2)
        assert chunk_size >= self.seq0.size
        
        for i, bit in enumerate(iterbits(payload)):
            dst = (cH2, cV2)[i % 2]
            seq = (self.seq0, self.seq1)[bit]
            dst[(i//2)*chunk_size:(i//2)*chunk_size + seq.size] += k * seq
        return idwt2((cA, (cH2.reshape(w, h), cV2.reshape(w, h), cD)), self.mother)[:img.shape[0],:img.shape[1]]
    
    def embed(self, img, payload, k = 10):
        if len(payload) > self.msg_bytes:
            raise ValueError("payload too long")
        if isinstance(payload, str):
            payload = bytearray(payload)
        payload.extend([0] * (self.msg_bytes - len(payload)))
        encoded = self.rscodec.encode(payload)
        masked = [v ^ m for v, m in zip(encoded, self.mask)]

        if len(img.shape) == 2:
            return self._embed(img, masked, k)
        elif len(img.shape) == 3:
            res = numpy.zeros(img.shape)
            for i in range(img.shape[2]):
                layer = self._embed(img[:,:,i], masked, k)
                res[:,:,i] = layer
            return res
        else:
            raise TypeError("image must be a 2d or 3d array")

    def _extract(self, img):
        cA, (cH, cV, cD) = dwt2(img, self.mother)
        w, h = cH.shape
        cH2 = cH.reshape(cH.size)
        cV2 = cV.reshape(cV.size)
        chunk_size = cH2.size // (self.total_bits // 2)
        
        maskiter = iter(self.mask)
        payload = bytearray()
        byte = 0
        for i in range(self.total_bits):
            src = (cH2, cV2)[i % 2]
            chunk = src[(i//2)*chunk_size:(i//2)*chunk_size + self.seq0.size]
            corr0, _ = pearsonr(chunk, self.seq0)
            corr1, _ = pearsonr(chunk, self.seq1)
            bit = int(corr1 > corr0)
            byte = bit | (byte << 1)
            if i % 8 == 7:
                payload.append(byte ^ maskiter.next())
                byte = 0
        print repr(payload)
        return self.rscodec.decode(payload)

    def extract(self, img):
        if len(img.shape) == 2:
            return self._extract(img)
        elif len(img.shape) == 3:
            for i in range(img.shape[2]):
                try:
                    return self._extract(img[:,:,i])
                except ReedSolomonError:
                    pass
            return self._extract(mean(img, 2))
        else:
            raise TypeError("image must be a 2d or 3d array")


#'bior1.1', 'bior1.3', 'bior1.5', 'bior2.2', 'bior2.4', 'bior2.6', 'bior2.8', 'bior3.1', 
#'bior3.3', 'bior3.5', 'bior3.7', 'bior3.9', 'bior4.4', 'bior5.5', 'bior6.8', 'coif1', 'coif2', 
#'coif3', 'coif4', 'coif5', 'db1', 'db2', 'db3', 'db4', 'db5', 'db6', 'db7', 'db8', 'db9', 
#'db10', 'db11', 'db12', 'db13', 'db14', 'db15', 'db16', 'db17', 'db18', 'db19', 'db20', 'dmey', 
#'haar', 'rbio1.1', 'rbio1.3', 'rbio1.5', 'rbio2.2', 'rbio2.4', 'rbio2.6', 'rbio2.8', 'rbio3.1', 
#'rbio3.3', 'rbio3.5', 'rbio3.7', 'rbio3.9', 'rbio4.4', 'rbio5.5', 'rbio6.8', 'sym2', 'sym3', 
#'sym4', 'sym5', 'sym6', 'sym7', 'sym8', 'sym9', 'sym10', 'sym11', 'sym12', 'sym13', 'sym14', 
#'sym15', 'sym16', 'sym17', 'sym18', 'sym19', 'sym20'


def embed_img(w, src, payload, k):
    embedded = w.embed(misc.imread(src), payload, k)
    misc.imsave("out.png", embedded)
    misc.imsave("out.jpg", embedded)


if __name__ == "__main__":
    w = Watermarker(8, 4, 239047238847, "db6")
    img = w.embed(misc.imread("pics/sky.png"), "helloman", 10)
    misc.imsave("out.png", img)
    misc.imsave("out.jpg", img)
    print w.extract(misc.imread("out.jpg"))

    
#    img = misc.imread("unrot.png")
#    sob = sobel(img)
#    bw = sob > threshold_otsu(sob)
#    misc.imsave("sob.png", bw)
#    lines = probabilistic_hough(bw, line_length = 200)
#    sorted_lines = sorted(lines, key = lambda l: distance(line_to_vector(l)), reverse = True)[:4]
#    min_y = bw.shape[0]
#    max_y = 0
#    min_x = bw.shape[1]
#    max_x = 0
#    for l in sorted_lines:
#        (x1, y1), (x2, y2) = l
#        if x1 < min_x:
#            min_x = x1
#        if x1 > max_x:
#            max_x = x1
#        if x2 < min_x:
#            min_x = x2
#        if x2 > max_x:
#            max_x = x2
#        if y1 < min_y:
#            min_y = y1
#        if y1 > max_y:
#            max_y = y1
#        if y2 < min_y:
#            min_y = y2
#        if y2 > max_y:
#            max_y = y2
#    img2 = img[min_y+1:max_y, min_x+1:max_x]
#    print img2.shape
#    misc.imsave("cut.png", img2)
#    img = w.embed(misc.lena(), "helloman", 2000)
#    #img2 = misc.imresize(misc.imresize(img, (530, 530)), (512, 512))
#    img2 = misc.imrotate(misc.imrotate(img, 1), -1)
#    misc.imsave("out.png",img2)
#    print w.extract(img2)

#    img = misc.imread("pics/thirteen.png")
#    cA, (cH, cV, cD) = dwt2(img, "haar")
#    rand = Random(23895712)
#    seq = numpy.array([[rand.choice([0,0,0,0,1]) for _ in range(cA.shape[1])] for _ in range(cA.shape[0])])
#    cA += 3 * seq
#    img2 = idwt2((cA, (cH, cV, cD)), "haar")
#    img2 = w.embed(img2, "helloman", 12)
#    
#    img3 = expand_rotate(img2, 7)
#    misc.imsave("rot.png", img3)
#    seq = seq.reshape(seq.size)
#
#    results = []
#    for a in range(340, 360):
#        rot = misc.imrotate(img3, a)
#        cA, (cH, cV, cD) = dwt2(rot, "haar")
#        corr, _ = pearsonr(cA.reshape(cA.size)[:seq.size], seq)
#        if corr != corr:  # NaN
#            corr = 0.95
#        print ".",
#        results.append((corr, a))
#    
#    angle = max(results, key = lambda x:x[0])[1]
#    print "angle =", angle
#    img4 = misc.imrotate(img3, angle)
#    misc.imsave("unrot.png", img4)
    #print w.extract(img2)
    #print w.extract(img4)
    
    #w = Watermarker(8, 4, 239047238847, "db6")
    #embed_img(w, "pics/munich.jpg", "foobar", 30)
    #print w.extract(misc.imread("lenascan2.png"))
    #print w.extract(misc.imread("lenascan2.png"))
    #print w.extract(misc.imread("crap26.png"))
    
    #rot = expand_rotate(img2, 7.5)
    #misc.imsave("out2.png", rot)
    #img3 = align(rot)
    #print img3.shape
    #misc.imsave("out3.png", img3)
    #print repr(w.extract(img3))
    
    #misc.imsave("out.png", img2)
    #misc.imsave("out.jpg", img2)
    #img3 = misc.imread("out.jpg")
    #img3 = misc.imread("pic3.png")
    #print repr(w.extract(img3))

    
    #rot = expand_rotate(orig, 7)
    #img2 = align(rot)
    #print img2.shape
    #misc.imsave("out.png", img2)
    

