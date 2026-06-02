import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Mic, MicOff, Phone, PhoneOff, MessageSquare, Shield, Lightbulb, Home, Activity } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useGeminiLive } from '@/src/hooks/useGeminiLive';
import { cn } from '@/lib/utils';

export default function App() {
  const { isConnected, isConnecting, messages, volume, connect, disconnect } = useGeminiLive();
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div className="min-h-screen bg-[#E4E3E0] text-[#141414] font-sans selection:bg-[#141414] selection:text-[#E4E3E0] p-4 md:p-8 flex items-center justify-center">
      <div className="max-w-5xl w-full grid grid-cols-1 lg:grid-cols-12 gap-8">
        
        {/* Left Column: Brand & Info */}
        <div className="lg:col-span-4 space-y-6">
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-[#141414]/60 font-mono text-xs uppercase tracking-widest">
              <Activity className="w-4 h-4" />
              <span>System Active</span>
            </div>
            <h1 className="text-5xl font-serif italic tracking-tight leading-none">Aura Tech</h1>
            <p className="text-sm text-[#141414]/70 font-mono">Next-Generation Smart Home Ecosystems</p>
          </div>

          <div className="space-y-4 pt-8 border-t border-[#141414]/10">
            <div className="flex items-start gap-3">
              <div className="p-2 bg-[#141414] text-[#E4E3E0] rounded-sm">
                <Home className="w-4 h-4" />
              </div>
              <div>
                <h3 className="font-medium text-sm">Aura Hub</h3>
                <p className="text-xs text-[#141414]/60">The central brain of your living space.</p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <div className="p-2 bg-[#141414] text-[#E4E3E0] rounded-sm">
                <Lightbulb className="w-4 h-4" />
              </div>
              <div>
                <h3 className="font-medium text-sm">Aura Lights</h3>
                <p className="text-xs text-[#141414]/60">Adaptive lighting that follows your rhythm.</p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <div className="p-2 bg-[#141414] text-[#E4E3E0] rounded-sm">
                <Shield className="w-4 h-4" />
              </div>
              <div>
                <h3 className="font-medium text-sm">Aura Security</h3>
                <p className="text-xs text-[#141414]/60">AI-powered protection for what matters most.</p>
              </div>
            </div>
          </div>

          <div className="pt-8">
            <Card className="bg-[#141414] text-[#E4E3E0] border-none rounded-none">
              <CardHeader className="pb-2">
                <CardTitle className="text-lg font-serif italic">Specialist Support</CardTitle>
                <CardDescription className="text-[#E4E3E0]/60 text-xs font-mono">
                  Speak with our AI agent to learn more about our ecosystem.
                </CardDescription>
              </CardHeader>
            </Card>
          </div>
        </div>

        {/* Right Column: Interaction */}
        <div className="lg:col-span-8 flex flex-col gap-6">
          <Card className="flex-1 bg-white border-[#141414] border-[1px] shadow-none rounded-none flex flex-col overflow-hidden">
            <CardHeader className="border-b border-[#141414] flex flex-row items-center justify-between py-4">
              <div className="flex items-center gap-2">
                <div className={cn(
                  "w-2 h-2 rounded-full",
                  isConnected ? "bg-green-500 animate-pulse" : "bg-red-500"
                )} />
                <span className="font-mono text-[10px] uppercase tracking-tighter">
                  {isConnected ? "Connection Established" : "Disconnected"}
                </span>
              </div>
              <Badge variant="outline" className="font-mono text-[10px] border-[#141414] rounded-none">
                {isConnecting ? "Initializing..." : isConnected ? "Live" : "Standby"}
              </Badge>
            </CardHeader>

            <CardContent className="flex-1 p-0 flex flex-col min-h-[400px]">
              <ScrollArea className="flex-1 p-6" ref={scrollRef}>
                <div className="space-y-6">
                  {messages.length === 0 && !isConnecting && !isConnected && (
                    <div className="h-full flex flex-col items-center justify-center text-center space-y-4 py-20">
                      <div className="w-16 h-16 rounded-full border border-[#141414]/10 flex items-center justify-center">
                        <Mic className="w-6 h-6 text-[#141414]/20" />
                      </div>
                      <div className="space-y-1">
                        <p className="font-serif italic text-xl">Ready to assist you</p>
                        <p className="text-xs text-[#141414]/40 font-mono">Click the button below to start a voice session</p>
                      </div>
                    </div>
                  )}

                  {messages.map((msg, i) => (
                    <motion.div
                      key={i}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      className={cn(
                        "flex flex-col gap-1",
                        msg.role === 'user' ? "items-end" : "items-start"
                      )}
                    >
                      <div className={cn(
                        "max-w-[80%] p-3 text-sm",
                        msg.role === 'user' 
                          ? "bg-[#141414] text-[#E4E3E0] font-mono" 
                          : "bg-[#141414]/5 text-[#141414] font-serif italic"
                      )}>
                        {msg.text}
                      </div>
                      <span className="text-[9px] font-mono opacity-30">
                        {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </motion.div>
                  ))}
                </div>
              </ScrollArea>

              {/* Visualizer */}
              <div className="h-24 border-t border-[#141414] bg-[#141414]/5 flex items-center justify-center gap-1 px-8">
                {isConnected ? (
                  Array.from({ length: 40 }).map((_, i) => (
                    <motion.div
                      key={i}
                      animate={{ 
                        height: isConnected ? Math.max(4, volume * 100 * (Math.random() * 0.5 + 0.5)) : 4 
                      }}
                      className="w-1 bg-[#141414] opacity-80"
                    />
                  ))
                ) : (
                  <div className="font-mono text-[10px] uppercase opacity-20 tracking-widest">
                    Audio Input Inactive
                  </div>
                )}
              </div>
            </CardContent>

            <CardFooter className="border-t border-[#141414] p-4 flex justify-between items-center bg-white">
              <div className="flex items-center gap-4">
                <div className="flex flex-col">
                  <span className="text-[10px] font-mono uppercase opacity-40">Session ID</span>
                  <span className="text-xs font-mono">AUR-772-X</span>
                </div>
              </div>

              <div className="flex gap-2">
                {!isConnected ? (
                  <Button 
                    onClick={connect} 
                    disabled={isConnecting}
                    className="bg-[#141414] hover:bg-[#141414]/90 text-[#E4E3E0] rounded-none font-mono text-xs h-10 px-6"
                  >
                    {isConnecting ? (
                      <motion.div
                        animate={{ rotate: 360 }}
                        transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                      >
                        <Activity className="w-4 h-4" />
                      </motion.div>
                    ) : (
                      <>
                        <Phone className="w-4 h-4 mr-2" />
                        Start Session
                      </>
                    )}
                  </Button>
                ) : (
                  <Button 
                    onClick={disconnect}
                    variant="outline"
                    className="border-[#141414] hover:bg-red-50 hover:text-red-600 rounded-none font-mono text-xs h-10 px-6"
                  >
                    <PhoneOff className="w-4 h-4 mr-2" />
                    End Session
                  </Button>
                )}
              </div>
            </CardFooter>
          </Card>

          <div className="grid grid-cols-3 gap-4">
            <div className="p-4 bg-white border border-[#141414]/10 flex flex-col gap-1">
              <span className="text-[9px] font-mono uppercase opacity-40">Latency</span>
              <span className="text-xs font-mono">~120ms</span>
            </div>
            <div className="p-4 bg-white border border-[#141414]/10 flex flex-col gap-1">
              <span className="text-[9px] font-mono uppercase opacity-40">Model</span>
              <span className="text-xs font-mono">G-3.1-Live</span>
            </div>
            <div className="p-4 bg-white border border-[#141414]/10 flex flex-col gap-1">
              <span className="text-[9px] font-mono uppercase opacity-40">Voice</span>
              <span className="text-xs font-mono">Zephyr</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
