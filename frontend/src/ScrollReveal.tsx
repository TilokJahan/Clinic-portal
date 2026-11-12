import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'

export function ScrollReveal({ children }: { children: React.ReactNode }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const { pathname } = useLocation()

  useEffect(() => {
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    window.scrollTo({ top: 0, behavior: reducedMotion ? 'auto' : 'smooth' })
    const container = containerRef.current
    if (!container) return

    const items = new Set<Element>()
    const show = (element: Element) => {
      if (items.has(element)) return
      items.add(element)
      element.classList.add('scroll-reveal-item')
      if (!observer) {
        element.classList.add('is-visible')
        return
      }
      observer.observe(element)
    }

    const observer = typeof IntersectionObserver === 'undefined'
      ? null
      : new IntersectionObserver((entries) => {
          entries.forEach((entry) => {
            if (!entry.isIntersecting) return
            entry.target.classList.add('is-visible')
            observer?.unobserve(entry.target)
          })
        }, { threshold: 0.08, rootMargin: '0px 0px -36px 0px' })

    Array.from(container.children).forEach(show)
    container.classList.add('scroll-reveal-ready')

    const mutations = new MutationObserver((records) => {
      records.forEach((record) => record.addedNodes.forEach((node) => {
        if (node instanceof Element) show(node)
      }))
    })
    mutations.observe(container, { childList: true })

    return () => {
      mutations.disconnect()
      observer?.disconnect()
      container.classList.remove('scroll-reveal-ready')
    }
  }, [pathname])

  return <div className="scroll-scene" ref={containerRef}>{children}</div>
}
