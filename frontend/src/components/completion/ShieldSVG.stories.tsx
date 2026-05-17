import type { Meta, StoryObj } from '@storybook/react-vite'
import ShieldSVG from './ShieldSVG'

const meta: Meta<typeof ShieldSVG> = {
  title: 'Completion/ShieldSVG',
  component: ShieldSVG,
  args: { completedDate: '2026-04-14' },
  parameters: {
    docs: {
      description: {
        component:
          'The "Secured by Cliff" shield. Three sanctioned display sizes: 56×64 (small ghost inside the summary card), 80×96 (dashboard aside, wrapped in a button), 150×180 (celebration hero).',
      },
    },
  },
}

export default meta
type Story = StoryObj<typeof ShieldSVG>

export const CelebrationHero150: Story = {
  name: '150×180 · celebration hero',
  args: { width: 150, height: 180 },
}

export const DashboardAside80: Story = {
  name: '80×96 · dashboard aside',
  args: { width: 80, height: 96 },
}

export const SummaryMiniature56: Story = {
  name: '56×64 · summary miniature',
  args: { width: 56, height: 64 },
}

export const Decorative: Story = {
  name: 'Decorative (aria-hidden)',
  args: { ariaHidden: true, width: 80, height: 96 },
  parameters: {
    docs: {
      description: {
        story:
          'Use `ariaHidden` when the parent (e.g. a button with its own aria-label) owns the accessible name.',
      },
    },
  },
}
