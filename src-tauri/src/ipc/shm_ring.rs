//! 文件映射 SPSC f32 ring。
//!
//! Layout:
//! - 0..8   write_seq: u64 little-endian，生产者累计写入样本数
//! - 8..16  read_seq:  u64 little-endian，消费者累计读取样本数
//! - 16..   f32 data[capacity]

use crate::error::AppResult;
use memmap2::{MmapMut, MmapOptions};
use std::fs::OpenOptions;
use std::path::{Path, PathBuf};

const HEADER_BYTES: usize = 16;

pub struct ShmRing {
    path: PathBuf,
    capacity: usize,
    mmap: MmapMut,
}

impl ShmRing {
    pub fn create(path: PathBuf, capacity: usize) -> AppResult<Self> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let file_len = HEADER_BYTES + capacity * std::mem::size_of::<f32>();
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(true)
            .open(&path)?;
        file.set_len(file_len as u64)?;
        let mut mmap = unsafe { MmapOptions::new().len(file_len).map_mut(&file)? };
        mmap.fill(0);
        mmap.flush()?;
        Ok(Self {
            path,
            capacity,
            mmap,
        })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn capacity(&self) -> usize {
        self.capacity
    }

    pub fn available_read(&self) -> usize {
        self.write_seq().saturating_sub(self.read_seq()) as usize
    }

    pub fn write_lossy(&mut self, samples: &[f32]) -> usize {
        if samples.is_empty() || self.capacity == 0 {
            return 0;
        }
        let mut read_seq = self.read_seq();
        let mut write_seq = self.write_seq();
        let free = self.capacity.saturating_sub(write_seq.saturating_sub(read_seq) as usize);
        if samples.len() > free {
            let drop = (samples.len() - free) as u64;
            read_seq = read_seq.saturating_add(drop);
            self.set_read_seq(read_seq);
        }

        let mut written = 0;
        while written < samples.len() {
            let pos = (write_seq as usize) % self.capacity;
            let n = (self.capacity - pos).min(samples.len() - written);
            self.data_mut()[pos..pos + n].copy_from_slice(&samples[written..written + n]);
            written += n;
            write_seq = write_seq.saturating_add(n as u64);
        }
        self.set_write_seq(write_seq);
        written
    }

    pub fn read_into(&mut self, out: &mut Vec<f32>, max_samples: usize) -> usize {
        out.clear();
        let available = self.available_read().min(max_samples);
        if available == 0 {
            return 0;
        }
        out.reserve(available);
        let mut read_seq = self.read_seq();
        let data = self.data();
        let mut read = 0;
        while read < available {
            let pos = (read_seq as usize) % self.capacity;
            let n = (self.capacity - pos).min(available - read);
            out.extend_from_slice(&data[pos..pos + n]);
            read += n;
            read_seq = read_seq.saturating_add(n as u64);
        }
        self.set_read_seq(read_seq);
        read
    }

    fn write_seq(&self) -> u64 {
        read_u64(&self.mmap[0..8])
    }

    fn read_seq(&self) -> u64 {
        read_u64(&self.mmap[8..16])
    }

    fn set_write_seq(&mut self, value: u64) {
        self.mmap[0..8].copy_from_slice(&value.to_le_bytes());
    }

    fn set_read_seq(&mut self, value: u64) {
        self.mmap[8..16].copy_from_slice(&value.to_le_bytes());
    }

    fn data(&self) -> &[f32] {
        bytemuck::cast_slice(&self.mmap[HEADER_BYTES..])
    }

    fn data_mut(&mut self) -> &mut [f32] {
        bytemuck::cast_slice_mut(&mut self.mmap[HEADER_BYTES..])
    }
}

impl Drop for ShmRing {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.path);
    }
}

fn read_u64(bytes: &[u8]) -> u64 {
    let mut arr = [0_u8; 8];
    arr.copy_from_slice(bytes);
    u64::from_le_bytes(arr)
}
