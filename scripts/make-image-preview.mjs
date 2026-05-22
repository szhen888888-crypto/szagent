#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { mkdir, readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import sharp from 'sharp';

const PRESETS = {
  thumb: { max: 320, quality: 60 },
  preview: { max: 900, quality: 70 },
  qa: { max: 1400, quality: 80 },
};

function usage() {
  console.error('Usage: node scripts/make-image-preview.mjs <image-path> [thumb|preview|qa]');
}

const input = process.argv[2];
const presetName = process.argv[3] ?? 'preview';

if (!input) {
  usage();
  process.exit(1);
}

const preset = PRESETS[presetName];
if (!preset) {
  console.error(`Unknown preset: ${presetName}`);
  usage();
  process.exit(1);
}

const rootDir = path.resolve(import.meta.dirname, '..');
const outDir = path.join(rootDir, 'assets', 'previews');
const inputPath = path.resolve(input);

await stat(inputPath).catch(() => {
  console.error(`Image not found: ${inputPath}`);
  process.exit(1);
});

const source = await readFile(inputPath);
const hash = createHash('sha256').update(source).digest('hex').slice(0, 12);
const parsed = path.parse(inputPath);
const outputPath = path.join(outDir, `${parsed.name}.${hash}.${presetName}.jpg`);

await mkdir(outDir, { recursive: true });

await sharp(source, { failOn: 'none' })
  .rotate()
  .resize({
    width: preset.max,
    height: preset.max,
    fit: 'inside',
    withoutEnlargement: true,
  })
  .jpeg({
    quality: preset.quality,
    mozjpeg: true,
  })
  .toFile(outputPath);

console.log(outputPath);
