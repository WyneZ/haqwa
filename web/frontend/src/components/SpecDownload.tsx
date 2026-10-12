interface Props {
  specYaml: string
}

/** Download the exact YAML accepted by Seal, without another server request. */
export function SpecDownload({ specYaml }: Props) {
  function download() {
    const url = URL.createObjectURL(new Blob([specYaml], { type: 'application/yaml' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'haqwa.spec.yaml'
    document.body.append(link)
    link.click()
    window.setTimeout(() => {
      link.remove()
      URL.revokeObjectURL(url)
    }, 1000)
  }

  return (
    <div className="spec-download">
      <button type="button" className="btn btn--ghost" onClick={download}>
        Download spec (YAML)
      </button>
      <details>
        <summary>For developers</summary>
        <pre>
          <code>{'git clone https://github.com/WyneZ/haqwa && cd haqwa && uv sync\nuv run haqwa check haqwa.spec.yaml your-events.json'}</code>
        </pre>
        <p>Exit code 1 when a rule is broken, so it can run in CI.</p>
      </details>
    </div>
  )
}
