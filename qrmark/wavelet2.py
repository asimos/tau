import numpy
import math
from pywt import dwt2, idwt2
import scipy
from scipy.fftpack import fft2, ifft2, fftshift, ifftshift, dct, idct
from scipy.stats import pearsonr
from scipy import misc, mean
from random import Random
from reedsolo import RSCodec, ReedSolomonError


def iterbits(data):
    for n in data:
        for i in (7,6,5,4,3,2,1,0):
            yield (n >> i) & 1

class Watermarker(object):
    EPSILON = 0.001
    def __init__(self, max_payload, ec_bytes, seed = 1910819922, mother = "haar"):
        self.mother = mother
        self.rscodec = RSCodec(ec_bytes)
        self.max_payload = max_payload
        self.total_bits = (max_payload + ec_bytes) * 8
        self.seed = seed

    def _embed(self, img, payload, k):
        rand = Random(self.seed)
        cA, (cH, cV, cD) = dwt2(img, self.mother)
        cD2 = cD.reshape(cD.size)
        for bit in iterbits(payload):
            seq = numpy.array([int(rand.random() > 0.95) for _ in range(cD2.size)]) 
            if bit:
                cD2 += k * seq
        return idwt2((cA, (cH, cV, cD2.reshape(cD.shape))), self.mother)[:img.shape[0],:img.shape[1]]
    
    def embed(self, img, payload, k):
        if len(payload) > self.max_payload:
            raise ValueError("payload too long")
        payload = bytearray(payload) + "\x00" * (self.max_payload - len(payload))
        encoded = self.rscodec.encode(payload)
        
        if len(img.shape) == 2:
            return self._embed(img, encoded, k)
        elif len(img.shape) == 3:
            output = numpy.zeros(img.shape)
            for i in range(img.shape[2]):
                output[:,:,i] = self._embed(img[:,:,i], encoded, k)
            return output
        else:
            raise TypeError("img must be a 2d or 3d array")
    
    def _extract(self, img):
        rand = Random(self.seed)
        cA, (cH, cV, cD) = dwt2(img, self.mother)
        cD2 = cD.reshape(cD.size)
        byte = 0
        output = bytearray()
        for i in range(self.total_bits):
            seq = numpy.array([int(rand.random() > 0.95) for _ in range(cD2.size)]) 
            corr, _ = pearsonr(cD2, seq)
            bit = int(corr > 0.1)
            byte = (byte << 1) | bit
            if i % 8 == 7:
                output.append(byte)
                byte = 0
        print repr(output)
        return output
    
    def extract(self, img):
        if len(img.shape) == 2:
            return self.rscodec.decode(self._extract(img))
        elif len(img.shape) == 3:
            for i in range(img.shape[2]):
                try:
                    return self.rscodec.decode(self._extract(img[:,:,i]))
                except ReedSolomonError:
                    pass
            return self.rscodec.decode(self._extract(mean(img, 2)))
        else:
            raise TypeError("img must be a 2d or 3d array")
            

#'bior1.1', 'bior1.3', 'bior1.5', 'bior2.2', 'bior2.4', 'bior2.6', 'bior2.8', 'bior3.1', 
#'bior3.3', 'bior3.5', 'bior3.7', 'bior3.9', 'bior4.4', 'bior5.5', 'bior6.8', 'coif1', 'coif2', 
#'coif3', 'coif4', 'coif5', 'db1', 'db2', 'db3', 'db4', 'db5', 'db6', 'db7', 'db8', 'db9', 
#'db10', 'db11', 'db12', 'db13', 'db14', 'db15', 'db16', 'db17', 'db18', 'db19', 'db20', 'dmey', 
#'haar', 'rbio1.1', 'rbio1.3', 'rbio1.5', 'rbio2.2', 'rbio2.4', 'rbio2.6', 'rbio2.8', 'rbio3.1', 
#'rbio3.3', 'rbio3.5', 'rbio3.7', 'rbio3.9', 'rbio4.4', 'rbio5.5', 'rbio6.8', 'sym2', 'sym3', 
#'sym4', 'sym5', 'sym6', 'sym7', 'sym8', 'sym9', 'sym10', 'sym11', 'sym12', 'sym13', 'sym14', 
#'sym15', 'sym16', 'sym17', 'sym18', 'sym19', 'sym20'


if __name__ == "__main__":
    w = Watermarker(6, 3, 8294731, "haar")
    img2 = w.embed(misc.lena(), "123456", 15)
    #img2 = w.embed(misc.imread("pics/munich.jpg"), "123456", 10)
    misc.imsave("out.png", img2)
    misc.imsave("out.jpg", img2)
    print w.extract(misc.imread("out.jpg"))




