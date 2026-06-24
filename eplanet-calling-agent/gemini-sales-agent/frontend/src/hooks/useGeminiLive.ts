import { useState, useCallback, useRef, useEffect } from 'react';
import { arrayBufferToBase64, base64ToArrayBuffer, float32ToInt16, int16ToFloat32 } from '@/src/lib/audio-utils';

export type Message = {
  role: 'user' | 'model';
  text: string;
  timestamp: Date;
};

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const WS_URL = API_URL.replace(/^http/, 'ws');

export function useGeminiLive() {
  const [isConnected, setIsConnected] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [volume, setVolume] = useState(0);
  
  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const audioQueueRef = useRef<Float32Array[]>([]);
  const isPlayingRef = useRef(false);

  const cleanup = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track: MediaStreamTrack) => track.stop());
      streamRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    setIsConnected(false);
    setIsConnecting(false);
    isPlayingRef.current = false;
    audioQueueRef.current = [];
    setVolume(0);
  }, []);

  const playNextInQueue = useCallback(() => {
    if (!audioContextRef.current || audioQueueRef.current.length === 0 || isPlayingRef.current) {
      return;
    }

    isPlayingRef.current = true;
    const chunk = audioQueueRef.current.shift()!;
    const buffer = audioContextRef.current.createBuffer(1, chunk.length, 24000); // Gemini output is 24kHz
    buffer.getChannelData(0).set(chunk);

    const source = audioContextRef.current.createBufferSource();
    source.buffer = buffer;
    source.connect(audioContextRef.current.destination);
    
    source.onended = () => {
      isPlayingRef.current = false;
      playNextInQueue();
    };
    
    source.start();
  }, []);

  const connect = useCallback(async (agentId: number = 1) => {
    if (isConnected || isConnecting) return;
    setIsConnecting(true);
    try {
      const token = localStorage.getItem('aura_token') || '';
      audioContextRef.current = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 16000 });
      streamRef.current = await navigator.mediaDevices.getUserMedia({ audio: true });

      const ws = new WebSocket(`${WS_URL}/ws/live?agent_id=${agentId}&token=${encodeURIComponent(token)}`);
      wsRef.current = ws;

      ws.onmessage = async (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === 'connected') {
          setIsConnected(true);
          setIsConnecting(false);
          // Start mic capture
          const source = audioContextRef.current!.createMediaStreamSource(streamRef.current!);
          const processor = audioContextRef.current!.createScriptProcessor(4096, 1, 1);
          processorRef.current = processor;
          processor.onaudioprocess = (e: AudioProcessingEvent) => {
            const float32 = e.inputBuffer.getChannelData(0);
            let sum = 0;
            for (let i = 0; i < float32.length; i++) sum += float32[i] * float32[i];
            setVolume(Math.sqrt(sum / float32.length));
            if (ws.readyState === WebSocket.OPEN) {
              const pcm = float32ToInt16(float32);
              ws.send(JSON.stringify({ type: 'audio', data: arrayBufferToBase64(pcm.buffer) }));
            }
          };
          source.connect(processor);
          processor.connect(audioContextRef.current!.destination);
        } else if (msg.type === 'audio' && msg.data) {
          const ab = base64ToArrayBuffer(msg.data);
          const int16 = new Int16Array(ab);
          const float32 = int16ToFloat32(int16);
          audioQueueRef.current.push(float32);
          playNextInQueue();
        } else if (msg.type === 'transcript_user') {
          setMessages(prev => [...prev, { role: 'user', text: msg.text, timestamp: new Date() }]);
        } else if (msg.type === 'transcript_model') {
          setMessages(prev => [...prev, { role: 'model', text: msg.text, timestamp: new Date() }]);
        } else if (msg.type === 'interrupted') {
          audioQueueRef.current = [];
          isPlayingRef.current = false;
        } else if (msg.type === 'disconnected') {
          cleanup();
        }
      };

      ws.onerror = () => cleanup();
      ws.onclose = () => cleanup();

    } catch (err) {
      console.error('Failed to connect:', err);
      cleanup();
    }
  }, [cleanup, isConnected, isConnecting, playNextInQueue]);

  const disconnect = useCallback(() => {
    cleanup();
  }, [cleanup]);

  useEffect(() => {
    return () => cleanup();
  }, [cleanup]);

  return {
    isConnected,
    isConnecting,
    messages,
    volume,
    connect,
    disconnect
  };
}
