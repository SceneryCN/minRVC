//! SPSC 环形缓冲，连接「cpal 回调线程」与「sidecar IPC tokio 任务」。
//!
//! - capture 回调  -> producer.push_slice(&samples)
//! - sidecar  task -> consumer.pop_slice(&mut buf)
//!
//! 双向各开一个：
//! - mic_to_engine:  原始麦克风 PCM
//! - engine_to_out:  变声后 PCM
//!
//! 容量 = 采样率 * 通道 * latency_seconds，向上取 2 的幂。

use ringbuf::traits::Split;
use ringbuf::storage::Heap;
use ringbuf::{HeapRb, SharedRb};
use std::sync::Arc;

pub type SampleProducer = ringbuf::wrap::caching::Caching<Arc<SharedRb<Heap<f32>>>, true, false>;
pub type SampleConsumer = ringbuf::wrap::caching::Caching<Arc<SharedRb<Heap<f32>>>, false, true>;

pub struct AudioRingBuffer {
    capacity: usize,
}

impl AudioRingBuffer {
    pub fn new(sample_rate: u32, channels: u16, latency_secs: f32) -> Self {
        let want = (sample_rate as f32 * channels as f32 * latency_secs).ceil() as usize;
        let capacity = want.next_power_of_two().max(4096);
        Self { capacity }
    }

    pub fn split(&self) -> (SampleProducer, SampleConsumer) {
        let rb = HeapRb::<f32>::new(self.capacity);
        rb.split()
    }
}
