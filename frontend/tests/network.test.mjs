import assert from 'node:assert/strict'
import test from 'node:test'
import {build} from 'esbuild'
import {createRequire} from 'node:module'

test('lost mutation response is explicit and requests reconciliation without retry',async()=>{
  const result=await build({entryPoints:['src/api.ts'],bundle:true,write:false,platform:'node',format:'cjs',packages:'external',jsx:'automatic'})
  const m={exports:{}}
  new Function('require','module','exports',result.outputFiles[0].text)(createRequire(import.meta.url),m,m.exports)
  const previous={fetch:globalThis.fetch,window:globalThis.window,localStorage:globalThis.localStorage}
  let calls=0,refreshes=0
  globalThis.window=new EventTarget()
  window.addEventListener('project-updated',()=>refreshes++)
  globalThis.localStorage={getItem:()=> '1'}
  globalThis.fetch=async()=>{calls++;throw new TypeError('Failed to fetch')}
  try {
    await assert.rejects(m.exports.api.createTask({title:'Response lost'}),error=>
      error.code==='NETWORK_RESULT_UNKNOWN' && /проверьте/i.test(error.message))
    assert.equal(calls,1)
    assert.equal(refreshes,1)
    globalThis.fetch=async()=>({ok:true,json:async()=>{throw new SyntaxError('truncated response')}})
    await assert.rejects(m.exports.api.createTask({title:'Truncated response'}),
      error=>error.code==='NETWORK_RESULT_UNKNOWN')
    assert.equal(refreshes,2)
    globalThis.fetch=async()=>{throw new TypeError('offline')}
    await assert.rejects(m.exports.api.tasks(),error=>error.code==='NETWORK_ERROR')
    assert.equal(refreshes,2) // Failed reconciliation must not recursively refresh itself.
  } finally {
    Object.assign(globalThis,previous)
  }
})
