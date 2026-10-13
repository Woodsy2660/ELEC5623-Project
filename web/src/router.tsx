import { createBrowserRouter } from 'react-router-dom'
import { CaptureRoute } from './routes/Capture.tsx'
import { HomeRoute } from './routes/Home.tsx'
import { ImportRoute } from './routes/Import.tsx'
import { MeetingsRoute } from './routes/Meetings.tsx'
import { RegisterRoute } from './routes/Register.tsx'
import { RequirementDetailRoute } from './routes/RequirementDetail.tsx'
import { ReviewRoute } from './routes/Review.tsx'
import { KitchenRoute } from './routes/Kitchen.tsx'
import { RootLayout } from './routes/RootLayout.tsx'
import { SettingsRoute } from './routes/Settings.tsx'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <RootLayout />,
    children: [
      { index: true, element: <HomeRoute /> },
      { path: 'projects/:projectId/register', element: <RegisterRoute /> },
      {
        path: 'projects/:projectId/requirements/:requirementId',
        element: <RequirementDetailRoute />,
      },
      { path: 'projects/:projectId/review', element: <ReviewRoute /> },
      { path: 'projects/:projectId/meetings', element: <MeetingsRoute /> },
      { path: 'projects/:projectId/import', element: <ImportRoute /> },
      { path: 'projects/:projectId/settings', element: <SettingsRoute /> },
      { path: 'projects/:projectId/capture', element: <CaptureRoute /> },
      { path: 'kitchen', element: <KitchenRoute /> },
    ],
  },
])
