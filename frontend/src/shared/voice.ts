/** Запись голоса в PCM 16 кГц — формат, который SpeechKit принимает как есть.
 *
 *  MediaRecorder отдаёт WebM/Opus, а SpeechKit его не понимает; перекодировать
 *  на сервере — тащить ffmpeg в образ. Проще снять сырой звук через Web Audio
 *  и уменьшить частоту дискретизации прямо в браузере. */

const TARGET_RATE = 16_000;
const MAX_SECONDS = 30;

export interface Recorder {
  stop: () => Promise<ArrayBuffer>;
  cancel: () => void;
  /** Громкость 0..1 для индикатора, обновляется во время записи. */
  level: () => number;
}

export function voiceSupported(): boolean {
  const ctx = (window as any).AudioContext ?? (window as any).webkitAudioContext;
  // mediaDevices нет на страницах без HTTPS — там микрофон недоступен вовсе
  return typeof navigator.mediaDevices?.getUserMedia === "function" && Boolean(ctx);
}

export async function startRecording(): Promise<Recorder> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });
  const Ctx: typeof AudioContext = window.AudioContext || (window as any).webkitAudioContext;
  const ctx = new Ctx();
  const source = ctx.createMediaStreamSource(stream);
  // ScriptProcessor устарел, но в отличие от AudioWorklet работает во всех
  // мобильных вебвью без отдельного файла-модуля
  const node = ctx.createScriptProcessor(4096, 1, 1);
  const chunks: Float32Array[] = [];
  let total = 0;
  let current = 0;

  node.onaudioprocess = (e) => {
    const data = e.inputBuffer.getChannelData(0);
    if (total < ctx.sampleRate * MAX_SECONDS) {
      chunks.push(new Float32Array(data));
      total += data.length;
    }
    let sum = 0;
    for (let i = 0; i < data.length; i += 8) sum += data[i] * data[i];
    current = Math.min(1, Math.sqrt(sum / (data.length / 8)) * 6);
  };
  source.connect(node);
  node.connect(ctx.destination);

  const release = () => {
    node.disconnect();
    source.disconnect();
    stream.getTracks().forEach((t) => t.stop());
    void ctx.close();
  };

  return {
    level: () => current,
    cancel: release,
    stop: async () => {
      release();
      return toPcm16(chunks, total, ctx.sampleRate);
    },
  };
}

function toPcm16(chunks: Float32Array[], total: number, rate: number): ArrayBuffer {
  const merged = new Float32Array(total);
  let offset = 0;
  for (const c of chunks) {
    merged.set(c, offset);
    offset += c.length;
  }
  // Понижение частоты усреднением — для речи этого достаточно
  const ratio = rate / TARGET_RATE;
  const outLen = Math.floor(merged.length / ratio);
  const out = new DataView(new ArrayBuffer(outLen * 2));
  for (let i = 0; i < outLen; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(merged.length, Math.floor((i + 1) * ratio));
    let acc = 0;
    for (let j = start; j < end; j++) acc += merged[j];
    const v = Math.max(-1, Math.min(1, acc / Math.max(1, end - start)));
    out.setInt16(i * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true);
  }
  return out.buffer;
}
