"""文件映射 SPSC f32 ring。

与 Rust `ipc/shm_ring.rs` 保持同一 layout：
- 0..8   write_seq: u64 little-endian
- 8..16  read_seq:  u64 little-endian
- 16..   float32 samples
"""

from __future__ import annotations

import mmap
import struct
from pathlib import Path
from typing import Optional

import numpy as np

HEADER_BYTES = 16


class ShmRing:
    def __init__(self, path: str, capacity_samples: int) -> None:
        self.path = Path(path)
        self.capacity = int(capacity_samples)
        self._file = self.path.open("r+b")
        self._mmap = mmap.mmap(self._file.fileno(), 0)
        self._data = memoryview(self._mmap)[HEADER_BYTES:]

    def close(self) -> None:
        self._data.release()
        self._mmap.close()
        self._file.close()

    def available_read(self) -> int:
        return max(0, self._write_seq() - self._read_seq())

    def read(self, max_samples: Optional[int] = None) -> np.ndarray:
        available = self.available_read()
        if max_samples is not None:
            available = min(available, int(max_samples))
        if available <= 0:
            return np.zeros(0, dtype=np.float32)

        read_seq = self._read_seq()
        pos = read_seq % self.capacity
        if pos + available <= self.capacity:
            out = np.frombuffer(
                self._data[pos * 4 : (pos + available) * 4],
                dtype=np.float32,
            ).copy()
        else:
            first = self.capacity - pos
            a = np.frombuffer(self._data[pos * 4 :], dtype=np.float32)
            b = np.frombuffer(
                self._data[: (available - first) * 4],
                dtype=np.float32,
            )
            out = np.concatenate([a, b]).astype(np.float32, copy=False)
        self._set_read_seq(read_seq + available)
        return out

    def write_lossy(self, samples: np.ndarray) -> int:
        if samples.size == 0:
            return 0
        data = np.asarray(samples, dtype=np.float32).reshape(-1)
        read_seq = self._read_seq()
        write_seq = self._write_seq()
        free = self.capacity - max(0, write_seq - read_seq)
        if data.size > free:
            self._set_read_seq(read_seq + data.size - free)

        written = 0
        while written < data.size:
            pos = write_seq % self.capacity
            n = min(self.capacity - pos, data.size - written)
            self._data[pos * 4 : (pos + n) * 4] = data[written : written + n].tobytes()
            write_seq += n
            written += n
        self._set_write_seq(write_seq)
        return written

    def _write_seq(self) -> int:
        return struct.unpack_from("<Q", self._mmap, 0)[0]

    def _read_seq(self) -> int:
        return struct.unpack_from("<Q", self._mmap, 8)[0]

    def _set_write_seq(self, value: int) -> None:
        struct.pack_into("<Q", self._mmap, 0, int(value))

    def _set_read_seq(self, value: int) -> None:
        struct.pack_into("<Q", self._mmap, 8, int(value))


class ShmTransport:
    def __init__(self, input_path: str, output_path: str, capacity_samples: int) -> None:
        self.input = ShmRing(input_path, capacity_samples)
        self.output = ShmRing(output_path, capacity_samples)

    def close(self) -> None:
        self.input.close()
        self.output.close()

