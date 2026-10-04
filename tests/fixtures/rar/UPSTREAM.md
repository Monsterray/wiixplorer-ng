# Compressed RAR test fixtures

Source: libarchive/libarchive commit
[`a61db9140707ed638c2ed6785bbfdbe0dc60458b`](https://github.com/libarchive/libarchive/tree/a61db9140707ed638c2ed6785bbfdbe0dc60458b).

Imported uuencoded fixtures from `libarchive/test/`:

| Local file | Upstream file | SHA-256 |
| --- | --- | --- |
| normal.rar.uu | test_read_format_rar_compress_normal.rar.uu | 1c36a76e84bf08d1fdf7597b43737fa174a0813bf2715bf181fd3afb6f6f1f11 |
| best.rar.uu | test_read_format_rar_compress_best.rar.uu | 0f50ec35cac7e60e857b13e4ffb4c679ea3bfc602bb7065d69e47aa9db5c3170 |

The source fixtures are unchanged. The native generator retains only the first
independent compressed file and adds a fresh end header, excluding the upstream
link/other entries. This derivative is marked in the generator. Expected bytes
are 20,111 and CRC32 is 5e05a663 for `LibarchiveAddingTest.html`; an independent
libarchive extraction confirmed these values. No archive library is imported
or replaced. Upstream's test-source notice is retained below.

```text
/*-
 * Copyright (c) 2003-2007 Tim Kientzle
 * Copyright (c) 2011 Andres Mejia
 * Copyright (c) 2011-2012 Michihiro NAKAJIMA
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED BY THE AUTHOR(S) ``AS IS'' AND ANY EXPRESS OR
 * IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
 * OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
 * IN NO EVENT SHALL THE AUTHOR(S) BE LIABLE FOR ANY DIRECT, INDIRECT,
 * INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
 * NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 * DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 * THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
 * THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */
```

The best-compression first member requests a 25 MiB PPM dictionary. The
native runner deliberately expects budget rejection and original preservation;
its small output size does not justify exceeding the 16 MiB decoder budget.
The normal-compression member is a positive decompression fixture.
