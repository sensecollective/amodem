import numpy as np
from numpy import linalg
import logging

log = logging.getLogger(__name__)

from . import sampling
from . import common
from .config import Ts, Nsym


class Filter(object):
    def __init__(self, b, a):
        self.b = np.array(b) / a[0]
        self.a = np.array(a[1:]) / a[0]

    def __call__(self, x):
        x_ = [0] * len(self.b)
        y_ = [0] * (len(self.a) + 1)
        for v in x:
            x_ = [v] + x_[:-1]
            y_ = y_[:-1]
            num = np.dot(x_, self.b)
            den = np.dot(y_, self.a)
            y = num - den
            y_ = [y] + y_
            yield y


def lfilter(b, a, x):
    f = Filter(b=b, a=a)
    y = list(f(x))
    return np.array(y)


def train(S, training):
    A = np.array([S[1:], S[:-1], training[:-1]]).T
    b = training[1:]
    b0, b1, a1 = linalg.lstsq(A, b)[0]
    return Filter(b=[b0, b1], a=[1, -a1])


class QAM(object):
    def __init__(self, symbols):
        self._enc = {}
        symbols = np.array(list(symbols))
        bits_per_symbol = np.log2(len(symbols))
        bits_per_symbol = np.round(bits_per_symbol)
        N = (2 ** bits_per_symbol)
        assert N == len(symbols)
        bits_per_symbol = int(bits_per_symbol)

        for i, v in enumerate(symbols):
            bits = tuple(int(i & (1 << j) != 0) for j in range(bits_per_symbol))
            self._enc[bits] = v

        self._dec = {v: k for k, v in self._enc.items()}
        self.symbols = symbols
        self.bits_per_symbol = bits_per_symbol

        reals = np.array(list(sorted(set(symbols.real))))
        imags = np.array(list(sorted(set(symbols.imag))))
        self.real_factor = 1.0 / np.mean(np.diff(reals))
        self.imag_factor = 1.0 / np.mean(np.diff(imags))
        self.real_offset = reals[0]
        self.imag_offset = imags[0]

        self.symbols_map = {}
        for S in symbols:
            real_index = round(S.real * self.real_factor + self.real_offset)
            imag_index = round(S.imag * self.imag_factor + self.imag_offset)
            self.symbols_map[real_index, imag_index] = (S, self._dec[S])

    def encode(self, bits):
        for _, bits_tuple in common.iterate(bits, self.bits_per_symbol, tuple):
            yield self._enc[bits_tuple]

    def decode(self, symbols, error_handler=None):
        real_factor = self.real_factor
        real_offset = self.real_offset

        imag_factor = self.imag_factor
        imag_offset = self.imag_offset

        symbols_map = self.symbols_map
        for S in symbols:
            real_index = round(S.real * real_factor + real_offset)
            imag_index = round(S.imag * imag_factor + imag_offset)
            decoded_symbol, bits = symbols_map[real_index, imag_index]
            if error_handler:
                error_handler(received=S, decoded=decoded_symbol)
            yield bits

class Demux(object):
    def __init__(self, src, freqs):
        interp = sampling.Interpolator()
        self.sampler = sampling.Sampler(src, interp)
        self.filters = [exp_iwt(-f, Nsym) / (0.5*Nsym) for f in freqs]
        self.filters = np.array(self.filters)

    def __iter__(self):
        return self

    def next(self):
        frame = self.sampler.take(size=Nsym)
        return np.dot(self.filters, frame)

    __next__ = next


class MODEM(object):
    def __init__(self, config):
        self.qam = QAM(config.symbols)
        self.baud = config.baud
        self.freqs = config.frequencies
        self.bits_per_baud = self.qam.bits_per_symbol * len(self.freqs)
        self.modem_bps = self.baud * self.bits_per_baud


def clip(x, lims):
    return min(max(x, lims[0]), lims[1])


def power(x):
    return np.dot(x.conj(), x).real / len(x)


def exp_iwt(freq, n):
    iwt = 2j * np.pi * freq * np.arange(n) * Ts
    return np.exp(iwt)


def norm(x):
    return np.sqrt(np.dot(x.conj(), x).real)


def coherence(x, freq):
    n = len(x)
    Hc = exp_iwt(-freq, n) / np.sqrt(0.5*n)
    norm_x = norm(x)
    if norm_x:
        return np.dot(Hc, x) / norm_x
    else:
        return 0.0


def linear_regression(x, y):
    ''' Find (a,b) such that y = a*x + b. '''
    x = np.array(x)
    y = np.array(y)
    ones = np.ones(len(x))
    M = np.array([x, ones]).T
    a, b = linalg.lstsq(M, y)[0]
    return a, b
