import { useState, useCallback, useRef, useEffect } from 'react';
import { GoogleGenAI, LiveServerMessage, Modality } from "@google/genai";
import { arrayBufferToBase64, base64ToArrayBuffer, float32ToInt16, int16ToFloat32 } from '@/src/lib/audio-utils';

export type Message = {
  role: 'user' | 'model';
  text: string;
  timestamp: Date;
};

export function useGeminiLive() {
  const [isConnected, setIsConnected] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [volume, setVolume] = useState(0);
  
  const aiRef = useRef<any>(null);
  const sessionRef = useRef<any>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const audioQueueRef = useRef<Float32Array[]>([]);
  const isPlayingRef = useRef(false);

  const cleanup = useCallback(() => {
    if (sessionRef.current) {
      sessionRef.current.close();
      sessionRef.current = null;
    }
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
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

  const connect = useCallback(async () => {
    if (isConnected || isConnecting) return;

    setIsConnecting(true);
    try {
      const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY! });
      aiRef.current = ai;

      // Setup Audio
      audioContextRef.current = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 16000 });
      streamRef.current = await navigator.mediaDevices.getUserMedia({ audio: true });
      
      const source = audioContextRef.current.createMediaStreamSource(streamRef.current);
      processorRef.current = audioContextRef.current.createScriptProcessor(4096, 1, 1);

      const sessionPromise = ai.live.connect({
        model: "gemini-3.1-flash-live-preview",
        callbacks: {
          onopen: () => {
            setIsConnected(true);
            setIsConnecting(false);
            console.log("Gemini Live connected");
          },
          onmessage: async (message: LiveServerMessage) => {
            // Handle Audio Output
            const parts = message.serverContent?.modelTurn?.parts;
            if (parts) {
              for (const part of parts) {
                if (part.inlineData?.data) {
                  const arrayBuffer = base64ToArrayBuffer(part.inlineData.data);
                  const pcmData = new Int16Array(arrayBuffer);
                  const floatData = int16ToFloat32(pcmData);
                  audioQueueRef.current.push(floatData);
                  playNextInQueue();
                }
                if (part.text) {
                  setMessages(prev => {
                    const last = prev[prev.length - 1];
                    if (last && last.role === 'model' && (new Date().getTime() - last.timestamp.getTime() < 2000)) {
                      return [...prev.slice(0, -1), { ...last, text: last.text + " " + part.text }];
                    }
                    return [...prev, { role: 'model', text: part.text, timestamp: new Date() }];
                  });
                }
              }
            }

            // Handle User Transcription
            const userTranscription = message.serverContent?.userTurn?.parts?.[0]?.text;
            if (userTranscription) {
              setMessages(prev => {
                const last = prev[prev.length - 1];
                if (last && last.role === 'user' && (new Date().getTime() - last.timestamp.getTime() < 2000)) {
                  return [...prev.slice(0, -1), { ...last, text: last.text + " " + userTranscription }];
                }
                return [...prev, { role: 'user', text: userTranscription, timestamp: new Date() }];
              });
            }

            // Handle Interruption
            if (message.serverContent?.interrupted) {
              audioQueueRef.current = [];
              isPlayingRef.current = false;
            }
          },
          onclose: () => {
            cleanup();
          },
          onerror: (err) => {
            console.error("Gemini Live error:", err);
            cleanup();
          }
        },
          config: {
            responseModalities: [Modality.AUDIO],
            speechConfig: {
              voiceConfig: { prebuiltVoiceConfig: { voiceName: "Zephyr" } },
            },
            systemInstruction: "You are a professional sales agent for 'Aura Tech', a company that sells high-end smart home ecosystems. Your goal is to be helpful, persuasive, and friendly. You should answer questions about Aura Tech products (Smart Hub, Aura Lights, Aura Security) and try to close a discovery call. Keep your responses concise and conversational, as this is a voice interaction.",
            outputAudioTranscription: {},
            inputAudioTranscription: {},
          },
      });

      const session = await sessionPromise;
      sessionRef.current = session;

      processorRef.current.onaudioprocess = (e) => {
        const inputData = e.inputBuffer.getChannelData(0);
        
        // Calculate volume for UI
        let sum = 0;
        for (let i = 0; i < inputData.length; i++) {
          sum += inputData[i] * inputData[i];
        }
        setVolume(Math.sqrt(sum / inputData.length));

        // Send to Gemini
        const pcmData = float32ToInt16(inputData);
        const base64Data = arrayBufferToBase64(pcmData.buffer);
        
        session.sendRealtimeInput({
          audio: { data: base64Data, mimeType: 'audio/pcm;rate=16000' }
        });
      };

      source.connect(processorRef.current);
      processorRef.current.connect(audioContextRef.current.destination);

    } catch (err) {
      console.error("Failed to connect:", err);
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
