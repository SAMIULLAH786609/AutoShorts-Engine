import { useTheme } from '../context/ThemeContext'

// Standalone toggle for pages with no sidebar (auth screens).
export default function ThemeToggleFloating() {
  const { theme, toggleTheme } = useTheme()

  return (
    <button
      className="theme-toggle-floating"
      onClick={toggleTheme}
      title={theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme'}
      aria-label="Toggle color theme"
    >
      {theme === 'light' ? '🌙' : '☀️'}
    </button>
  )
}
