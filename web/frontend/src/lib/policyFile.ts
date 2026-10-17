/** Reading a policy document in the browser before upload. Presentation only. */

export const POLICY_ACCEPT = '.txt,.md,.docx,.pdf'
export const MAX_POLICY_BYTES = 1_000_000

/** The file's bytes as base64, for the JSON upload body. */
export async function fileToBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  }
  return btoa(binary)
}
