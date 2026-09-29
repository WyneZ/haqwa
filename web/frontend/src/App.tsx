import { Header } from './components/Header'
import { DefineScreen } from './screens/DefineScreen'

export default function App() {
  return (
    <div className="app">
      <Header active={0} />
      <DefineScreen />
    </div>
  )
}
