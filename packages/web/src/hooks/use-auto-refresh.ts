import { useEffect, useRef, useState, useCallback } from 'react'

interface UseAutoRefreshOptions {
  interval?: number // ms
  enabled?: boolean
  pauseOnBlur?: boolean
}

export function useAutoRefresh(
  callback: () => void | Promise<void>,
  options: UseAutoRefreshOptions = {},
) {
  const { interval = 5000, enabled: initialEnabled = false, pauseOnBlur = true } = options

  const [enabled, setEnabled] = useState(initialEnabled)
  const [isPaused, setIsPaused] = useState(false)
  const callbackRef = useRef(callback)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Keep callback ref up to date
  useEffect(() => {
    callbackRef.current = callback
  }, [callback])

  // Handle visibility change
  useEffect(() => {
    if (!pauseOnBlur) return

    const handleVisibilityChange = () => {
      if (document.hidden) {
        setIsPaused(true)
      } else {
        setIsPaused(false)
        // Immediately refresh when tab becomes visible
        if (enabled) {
          callbackRef.current()
        }
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [pauseOnBlur, enabled])

  // Set up interval
  useEffect(() => {
    if (enabled && !isPaused) {
      intervalRef.current = setInterval(() => {
        callbackRef.current()
      }, interval)
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [enabled, isPaused, interval])

  const toggle = useCallback(() => {
    setEnabled((prev) => !prev)
  }, [])

  const start = useCallback(() => {
    setEnabled(true)
  }, [])

  const stop = useCallback(() => {
    setEnabled(false)
  }, [])

  return {
    enabled,
    isPaused,
    toggle,
    start,
    stop,
  }
}
