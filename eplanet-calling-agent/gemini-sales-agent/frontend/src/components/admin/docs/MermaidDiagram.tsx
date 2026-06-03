import { useEffect, useRef, useId } from 'react';
import mermaid from 'mermaid';

let mermaidInitialized = false;

function initMermaid() {
  if (mermaidInitialized) return;
  mermaid.initialize({
    startOnLoad: false,
    theme: 'dark',
    themeVariables: {
      primaryColor: '#7c3aed',
      primaryTextColor: '#e4e4e7',
      primaryBorderColor: '#a78bfa',
      lineColor: '#71717a',
      secondaryColor: '#18181b',
      tertiaryColor: '#09090b',
      background: '#07070b',
      mainBkg: '#18181b',
      nodeBorder: '#3f3f46',
      clusterBkg: '#121215',
      titleColor: '#fafafa',
      edgeLabelBackground: '#18181b',
    },
    flowchart: { curve: 'basis', padding: 16 },
    sequence: { actorMargin: 48, messageMargin: 40 },
  });
  mermaidInitialized = true;
}

export function MermaidDiagram({ chart, className }: { chart: string; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const id = useId().replace(/:/g, '');

  useEffect(() => {
    initMermaid();
    const el = ref.current;
    if (!el) return;
    let cancelled = false;
    (async () => {
      try {
        const { svg } = await mermaid.render(`mmd-${id}`, chart.trim());
        if (!cancelled) el.innerHTML = svg;
      } catch {
        if (!cancelled) el.textContent = 'Diagram failed to render.';
      }
    })();
    return () => { cancelled = true; };
  }, [chart, id]);

  return (
    <div
      ref={ref}
      className={`overflow-x-auto rounded-xl border border-white/10 bg-black/30 p-4 [&_svg]:max-w-full [&_svg]:h-auto ${className ?? ''}`}
    />
  );
}
