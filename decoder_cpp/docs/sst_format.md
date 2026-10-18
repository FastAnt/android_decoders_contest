# SST1 Container Format

Binary container for SpectroStream RVQ tokens.

## File Structure

```
[File Header: 64 bytes]
[Chunk 0: header + payload]
[Chunk 1: header + payload]
...
[Chunk N-1: header + payload]
```

## File Header (64 bytes, little-endian)

| Offset | Size | Type   | Field              | Value/Description              |
|--------|------|--------|--------------------|--------------------------------|
| 0      | 4    | char[4]| magic              | `"SST1"` (0x53 0x53 0x54 0x31)|
| 4      | 2    | uint16 | version            | 1                              |
| 6      | 2    | uint16 | header_size        | 64                             |
| 8      | 4    | uint32 | sample_rate        | 48000                          |
| 12     | 2    | uint16 | channels           | 2                              |
| 14     | 2    | uint16 | frame_rate         | 25                             |
| 16     | 2    | uint16 | max_rvq_depth      | 64                             |
| 18     | 2    | uint16 | bits_per_code      | 10                             |
| 20     | 4    | uint32 | chunk_frames       | 25                             |
| 24     | 4    | uint32 | total_frame_count  | Total codec frames in file     |
| 28     | 8    | uint64 | original_samples   | Original PCM sample count      |
| 36     | 4    | uint32 | chunk_count        | Number of chunks               |
| 40     | 4    | uint32 | layout             | 1 = codebook-major             |
| 44     | 20   | bytes  | reserved           | Zero-filled                    |

## Chunk Header (16 bytes, little-endian)

| Offset | Size | Type   | Field              | Description                    |
|--------|------|--------|--------------------|--------------------------------|
| 0      | 2    | uint16 | frames_in_chunk    | 1..chunk_frames (last may be shorter) |
| 2      | 2    | uint16 | stored_rvq_depth   | Always max_rvq_depth (64)      |
| 4      | 4    | uint32 | payload_bytes      | Size of packed token payload   |
| 8      | 4    | uint32 | payload_crc32      | CRC-32 of payload bytes        |
| 12     | 4    | uint32 | reserved           | 0                              |

## Token Packing

### Layout: Codebook-Major

Before packing, the token matrix `[frames_in_chunk, rvq_depth]` is transposed
to `[rvq_depth, frames_in_chunk]` (codebook-major order). This ensures that
the first N codebooks form a contiguous byte-aligned prefix for progressive
decoding.

### 10-bit Packing

Token values are in range [0, 1023] (10 bits each). They are packed into a
little-endian bitstream:

- Groups of 4 values are packed into 5 bytes (40 bits):
  ```
  value0[9:0] | value1[9:0] | value2[9:0] | value3[9:0]
  ```
- Stored as 5 little-endian bytes per group.
- If total values are not divisible by 4, the last group is zero-padded
  before packing.
- The payload is truncated to exactly `ceil(total_values * 10 / 8)` bytes.

### Payload Size Formula

```
payload_bytes = (frames_in_chunk * stored_rvq_depth * bits_per_code + 7) / 8
```

For a full chunk (25 frames, 64 depth, 10 bits):
```
25 * 64 * 10 = 16000 bits = 2000 bytes
```

## CRC-32

Each chunk payload has an independent CRC-32 checksum (same polynomial as
zlib/gzip: 0xEDB88320 reflected). Computed over the raw payload bytes only
(not the chunk header).

## Chunking

- Default: 25 frames per chunk (1 second of audio at 25 fps).
- Each chunk is independently checksummed.
- The last chunk may have fewer frames.
- `chunk_count = ceil(total_frame_count / chunk_frames)`.

## Notes

- Byte order: all fields are little-endian.
- `original_samples` is the total number of PCM sample pairs (frames in audio
  terminology), used to trim decoder output to the correct length.
- `layout = 1` means codebook-major packing order within each chunk.
- No trailing data is allowed after the last chunk.
