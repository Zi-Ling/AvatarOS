"use client";

import { cn } from "@/lib/utils";

interface AvatarOrbProps {
  state?: 'idle' | 'thinking' | 'working' | 'error';
  className?: string;
}

export function AvatarOrb({ state = 'idle', className }: AvatarOrbProps) {
  return (
    <div className={cn("relative flex items-center justify-center w-64 h-64", className)}>
      
      {/* Outer Glow (Breathing) */}
      <div className={cn(
        "absolute inset-0 rounded-full opacity-20 blur-3xl transition-colors duration-1000",
        state === 'idle' && "bg-indigo-500 animate-pulse-slow",
        state === 'thinking' && "bg-cyan-500 animate-pulse-fast",
        state === 'working' && "bg-emerald-500 animate-pulse",
        state === 'error' && "bg-red-500"
      )} />

      {/* Core Circle */}
      <div className={cn(
        "relative w-32 h-32 rounded-full flex items-center justify-center transition-all duration-1000 shadow-2xl",
        state === 'idle' && "bg-gradient-to-br from-indigo-500 to-purple-600 shadow-indigo-500/50 scale-100",
        state === 'thinking' && "bg-gradient-to-br from-cyan-400 to-blue-600 shadow-cyan-500/50 scale-110 rotate-180",
        state === 'working' && "bg-gradient-to-br from-emerald-400 to-teal-600 shadow-emerald-500/50 scale-95",
        state === 'error' && "bg-gradient-to-br from-orange-500 to-red-600 shadow-red-500/50"
      )}>
        {/* Inner Texture/Noise */}
        <div className="absolute inset-0 rounded-full bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-30 mix-blend-overlay" />
        
        {/* Ring 1 (Orbit) */}
        <div className={cn(
          "absolute inset-[-20px] border border-white/20 rounded-full transition-all duration-1000",
          state === 'thinking' ? "animate-spin-slow border-dashed border-t-transparent" : "border-solid"
        )} />
        
        {/* Ring 2 (Orbit) */}
        <div className={cn(
          "absolute inset-[-40px] border border-white/10 rounded-full transition-all duration-1000",
          state === 'working' ? "animate-reverse-spin border-dotted border-b-transparent" : "border-solid"
        )} />

      </div>
      
      {/* Status Text (Optional, overlay) */}
      <div className="absolute bottom-[-60px] text-center">
        <span className={cn(
            "text-sm font-medium tracking-[0.2em] uppercase transition-colors duration-500",
            state === 'idle' && "text-indigo-400",
            state === 'thinking' && "text-cyan-400",
            state === 'working' && "text-emerald-400",
            state === 'error' && "text-red-400"
        )}>
            {state === 'idle' && "Standby"}
            {state === 'thinking' && "Processing"}
            {state === 'working' && "Executing"}
            {state === 'error' && "System Alert"}
        </span>
      </div>

    </div>
  );
}

