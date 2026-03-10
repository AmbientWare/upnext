import './style.css'

const app = document.getElementById('app')

app.innerHTML = `
  <h1>UpNext</h1>
  <p>Frontend served by <code>api.static()</code></p>
  <p id="status">Checking API...</p>
`

fetch('/health')
  .then(r => r.json())
  .then(data => {
    document.getElementById('status').textContent = `API status: ${data.status}`
  })
  .catch(() => {
    document.getElementById('status').textContent = 'API not reachable'
  })
