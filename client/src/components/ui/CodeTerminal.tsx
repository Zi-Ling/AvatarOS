"use client";

import React, { useState, useEffect, useRef } from 'react';
import { cn } from '@/lib/utils';
import { Terminal, Maximize2, Minimize2, Play } from 'lucide-react';

interface CodeTerminalProps {
  code: string;
  output?: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  title?: string;
}

export const CodeTerminal = React.memo(function CodeTerminal({ code, output, status, title = "Python Runtime" }: CodeTerminalProps) {
  const [displayedCode, setDisplayedCode] = useState("");
  const [displayedOutput, setDisplayedOutput] = useState("");
  const [isExpanded, setIsExpanded] = useState(false);
  const [showCursor, setShowCursor] = useState(true);
  
  const scrollRef = useRef<HTMLDivElement>(null);

  // Cursor blinking effect
  useEffect(() => {
    const interval = setInterval(() => {
      setShowCursor(prev => !prev);
    }, 500);
    return () => clearInterval(interval);
  }, []);

  // Code Typing effect
  useEffect(() => {
    if (!code) return;
    
    if (status === 'completed' || status === 'failed') {
      // If finished (and likely loaded from history), show code immediately
      // We only want to animate code if we are in 'running' state
      // But if we switched from running to completed, we rely on state preservation?
      // Actually, this logic might reset displayedCode on status change if we are not careful.
      // But since displayedCode state is preserved, setDisplayedCode(code) is idempotent if code hasn't changed.
      setDisplayedCode(code);
      return;
    }

    if (status === 'running') {
      // Reset if starting new run
      if (displayedCode.length === 0 && code.length > 0) {
          let currentIndex = 0;
          const typeNextChar = () => {
            if (currentIndex < code.length) {
              setDisplayedCode(code.slice(0, currentIndex + 1));
              currentIndex++;
              
              if (scrollRef.current) {
                scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
              }
              
              setTimeout(typeNextChar, Math.random() * 20 + 5);
            }
          };
          typeNextChar();
      }
    }
  }, [code, status]);

  // Output Typing effect (Simulated Streaming)
  useEffect(() => {
    if (!output) {
        setDisplayedOutput("");
        return;
    }

    // If status is completed/failed, we show output
    if (status === 'completed' || status === 'failed') {
        // If we already displayed full output, do nothing (prevents re-typing on re-renders)
        if (displayedOutput === output) return;

        // If output is very large, show immediately to avoid freezing/long wait
        if (output.length > 2000) {
            setDisplayedOutput(output);
            return;
        }

        // Typing animation for output
        let currentIndex = 0;
        const chunkSize = 3; // Type multiple chars at once for speed
        
        const typeNextChunk = () => {
            if (currentIndex < output.length) {
                const nextIndex = Math.min(output.length, currentIndex + chunkSize);
                setDisplayedOutput(output.slice(0, nextIndex));
                currentIndex = nextIndex;
                
                if (scrollRef.current) {
                    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
                }
                
                // 5ms delay for "fast streaming" feel
                setTimeout(typeNextChunk, 5); 
            }
        };
        typeNextChunk();
    }
  }, [output, status]);

  return (
    <div className={cn(
      "w-full rounded-lg overflow-hidden border transition-all duration-300 font-mono text-sm shadow-xl",
      isExpanded ? "fixed inset-4 z-50 h-auto" : "relative h-auto my-2",
      "bg-[#1e1e1e] border-[#333]"
    )}>
      {/* Terminal Header */}
      <div className="flex items-center justify-between px-4 py-2 bg-[#252526] border-b border-[#333]">
        <div className="flex items-center gap-2">
          <div className="flex gap-1.5">
            <div className="w-3 h-3 rounded-full bg-[#ff5f56]" />
            <div className="w-3 h-3 rounded-full bg-[#ffbd2e]" />
            <div className="w-3 h-3 rounded-full bg-[#27c93f]" />
          </div>
          <div className="ml-3 flex items-center gap-2 text-slate-400 text-xs">
             <Terminal className="w-3 h-3" />
             <span>{title}</span>
          </div>
        </div>
        
        <div className="flex items-center gap-2">
            {status === 'running' && (
                <span className="flex items-center gap-1 text-[10px] text-emerald-400 animate-pulse">
                    <Play className="w-3 h-3" /> Executing...
                </span>
            )}
            <button 
                onClick={() => setIsExpanded(!isExpanded)}
                className="text-slate-500 hover:text-slate-300 transition-colors"
            >
                {isExpanded ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
            </button>
        </div>
      </div>

      {/* Terminal Body */}
      <div 
        ref={scrollRef}
        className={cn(
            "p-4 overflow-auto bg-[#1e1e1e] text-[#d4d4d4]",
            isExpanded ? "h-[calc(100%-40px)]" : "max-h-[300px]"
        )}
      >
        <pre className="whitespace-pre-wrap break-all font-mono">
            {/* Code Section */}
            <div>
                <span className="text-[#569cd6] select-none">In [1]: </span>
                {displayedCode}
            </div>

            {/* Output Section */}
            {displayedOutput && (
                <div className="mt-2 border-t border-[#333] pt-2">
                    {/* Handle newlines correctly by using whitespace-pre-wrap */}
                    <div className="text-slate-300 whitespace-pre-wrap">{displayedOutput}</div>
                </div>
            )}

            {/* Cursor */}
            {status === 'running' && showCursor && (
                <span className="inline-block w-2 h-4 align-middle bg-[#d4d4d4] ml-0.5" />
            )}
        </pre>
        
        {(status === 'completed' || status === 'failed') && (
             <div className="mt-4 pt-4 border-t border-[#333] text-slate-400 italic text-xs select-none">
                {status === 'completed' ? (
                    <span className="text-emerald-400">Process finished with exit code 0</span>
                ) : (
                    <span className="text-red-400">Process failed</span>
                )}
             </div>
        )}
      </div>
    </div>
  );
});

