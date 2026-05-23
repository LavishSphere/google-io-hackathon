// Pull a frame off the playing <video> as a base64 JPEG.

const canvas = document.createElement('canvas');
const ctx = canvas.getContext('2d');

export function grabFrame(video: HTMLVideoElement, maxWidth = 768): string | null {
  if (!ctx || video.readyState < 2) return null;

  const ratio = video.videoHeight / video.videoWidth;
  const w = Math.min(maxWidth, video.videoWidth || maxWidth);
  const h = Math.round(w * ratio);
  canvas.width = w;
  canvas.height = h;
  ctx.drawImage(video, 0, 0, w, h);

  const dataUrl = canvas.toDataURL('image/jpeg', 0.6);
  return dataUrl.split(',')[1] ?? null;
}
