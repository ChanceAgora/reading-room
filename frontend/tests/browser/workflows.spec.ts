import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('in-page links retain search results and newer typing', async ({ page, request }) => {
  const before = (await (await request.get('/__testing/state')).json()).searches.length;
  await page.goto('/books');
  await page.getByRole('link', { name: 'Search', exact: true }).click();
  const query = page.getByRole('searchbox', { name: 'What are you researching?' });
  await query.fill('copper birds');
  await page.getByRole('button', { name: 'Search the library' }).click();
  await expect(page.locator('#search-results')).toContainText('copper birds');
  await query.fill('a newer thought');
  await page.getByRole('link', { name: 'Go to results', exact: true }).click();
  await expect(page.locator('#search-results')).toBeFocused();
  await expect(query).toHaveValue('a newer thought');
  const skip = page.getByRole('link', { name: 'Skip to main content', exact: true });
  await skip.focus();
  await skip.press('Enter');
  await expect(page.locator('#main')).toBeFocused();
  await expect(page.locator('#search-results')).toContainText('copper birds');
  await page.reload();
  await expect(query).toHaveValue('a newer thought');
  await expect(page.locator('#search-results')).toContainText('copper birds');
  expect((await (await request.get('/__testing/state')).json()).searches.length).toBe(before + 1);
});

test('separate search history entries restore their own drafts and results', async ({
  page,
  request,
}) => {
  const before = (await (await request.get('/__testing/state')).json()).searches.length;
  await page.goto('/search');
  const query = page.getByRole('searchbox', { name: 'What are you researching?' });
  await query.fill('copper birds');
  await page.getByRole('button', { name: 'Search the library' }).click();
  await expect(page.locator('#search-results')).toContainText('copper birds');
  await page.getByRole('link', { name: 'Search', exact: true }).click();
  await expect(page).toHaveURL('/');
  await expect(query).toHaveValue('');
  await expect(page.locator('#search-results')).toHaveCount(0);
  await query.fill('silver bells');
  await page.goBack();
  await expect(query).toHaveValue('copper birds');
  await expect(page.locator('#search-results')).toContainText('copper birds');
  await page.goForward();
  await expect(query).toHaveValue('silver bells');
  await expect(page.locator('#search-results')).toHaveCount(0);
  await page.reload();
  await expect(query).toHaveValue('silver bells');
  expect((await (await request.get('/__testing/state')).json()).searches.length).toBe(before + 1);
});

test('historical search URLs and unfinished drafts require explicit submission', async ({
  page,
  request,
}) => {
  const before = (await (await request.get('/__testing/state')).json()).searches.length;
  await page.goto('/search?q=copper%20birds&engine=exact&mode=exploratory&text_type=poetry');
  const query = page.getByRole('searchbox', { name: 'What are you researching?' });
  await expect(query).toHaveValue('copper birds');
  await expect(page.getByRole('status')).toContainText('no saved results');
  await expect(page.locator('#search-results')).toHaveCount(0);
  expect((await (await request.get('/__testing/state')).json()).searches.length).toBe(before);
  await query.fill('silver bells');
  await page.getByLabel('Search breadth').selectOption('focused');
  await page.getByText('Search method', { exact: true }).click();
  await page.getByRole('link', { name: 'The shelves', exact: true }).click();
  await expect(page).toHaveURL('/books');
  await page.goBack();
  await expect(query).toHaveValue('silver bells');
  await expect(page.getByLabel('Search breadth')).toHaveValue('focused');
  await expect(page.locator('details.search-method')).toHaveAttribute('open');
  await page.reload();
  await expect(query).toHaveValue('silver bells');
  await expect(page.getByLabel('Text type')).toHaveValue('poetry');
  await expect(page.locator('details.search-method')).toHaveAttribute('open');
  expect((await (await request.get('/__testing/state')).json()).searches.length).toBe(before);
  await page.getByLabel('Text type').selectOption('');
  await page.getByRole('button', { name: 'Search the library' }).click();
  await expect(page.locator('#search-results')).toContainText('silver bells');
  expect((await (await request.get('/__testing/state')).json()).searches.length).toBe(before + 1);
});

test('search, read, and return without replaying a submitted search', async ({ page, request }) => {
  const violations: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') violations.push(message.text());
  });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Find a thread.' })).toBeVisible();
  await page.getByRole('searchbox', { name: 'What are you researching?' }).fill('copper birds');
  await page.getByRole('button', { name: 'Search the library' }).click();
  await expect(page.locator('#search-results')).toContainText('copper birds');
  const before = (await (await request.get('/__testing/state')).json()).searches.length;
  await page
    .getByRole('link', { name: /Read .* in context/ })
    .first()
    .click();
  await expect(page).toHaveURL(/\/(units|read)\//);
  await expect(
    page.getByRole('link', { name: /Cite this (whole reading unit|passage)/ }),
  ).toBeVisible();
  await expect(page.locator('main')).toContainText('Copper birds gather beside the river.');
  await expect(page.locator('main script')).toHaveCount(0);
  expect(await page.evaluate(() => 'sourceWasExecuted' in window)).toBe(false);
  await page.goBack();
  await expect(page.locator('#search-results')).toContainText('copper birds');
  await page.reload();
  await expect(page.locator('#search-results')).toContainText('copper birds');
  await page.evaluate(() => {
    window.dispatchEvent(new Event('focus'));
    window.dispatchEvent(new Event('online'));
  });
  expect((await (await request.get('/__testing/state')).json()).searches.length).toBe(before);
  expect(
    violations.filter((message) => /Content Security|Refused to|Uncaught/.test(message)),
  ).toEqual([]);
});

test('all navigation areas load and controls remain named', async ({ page }) => {
  for (const [url, heading] of [
    ['/books', 'The shelves.'],
    ['/intake', 'Book intake'],
    ['/taxonomy', 'Subjects & connections'],
    ['/focus', 'Research focuses'],
    ['/history', 'Research history'],
    ['/status', 'Library status'],
  ] as const) {
    await page.goto(url);
    await expect(page.locator('main h1')).toContainText(
      new RegExp(heading.replace('.', '\\.'), 'i'),
    );
    await expect(page.locator('main')).not.toContainText('The request could not finish');
    const accessibility = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();
    expect(
      accessibility.violations.map((v) => `${v.id}: ${v.description}`),
      url,
    ).toEqual([]);
  }
});

test('theme, keyboard suggestions, and narrow layouts', async ({ page }) => {
  const policyErrors: string[] = [];
  page.on('console', (message) => {
    if (/Content Security|Refused to/.test(message.text())) policyErrors.push(message.text());
  });
  await page.goto('/books');
  await page.getByLabel('Appearance').selectOption('dark');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  const input = page.getByRole('combobox', { name: 'Find a book or creator' });
  await input.fill('Jane');
  await input.press('ArrowDown');
  await expect(page.getByRole('listbox')).toBeVisible();
  await input.press('Escape');
  await expect(page.getByRole('listbox')).toBeHidden();
  await page.setViewportSize({ width: 320, height: 800 });
  await expect(page.locator('main h1')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  expect(policyErrors).toEqual([]);
});

test('enlarged text reflows and reading prints without application controls', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 640, height: 900 });
  await page.goto('/books');
  await expect(page.locator('main h1')).toBeVisible();
  await page.evaluate(() => {
    document.documentElement.style.fontSize = '200%';
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByRole('button', { name: 'Find books', exact: true })).toBeVisible();
  const state = await (await request.get('/__testing/state')).json();
  await page.goto(`/read/${state.hit.id}`);
  await expect(page.locator('main')).toContainText('Copper birds gather beside the river.');
  await page.getByLabel('Appearance').selectOption('dark');
  await page.emulateMedia({ media: 'print' });
  await expect(page.locator('.masthead')).toBeHidden();
  await expect(page.locator('.research-record')).toBeHidden();
  await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(255, 255, 255)');
  await expect(page.locator('.reading-text')).toBeVisible();
});

test('review draft autosaves locally and survives reopening without applying', async ({
  page,
  request,
}) => {
  const initial = await (await request.get('/__testing/state')).json();
  await page.goto(`/review/${initial.work_id}`);
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.locator('main')).not.toContainText('The request could not finish');
  // The manual editor exposes current source values independently of AI suggestions.
  await page.getByText('View and edit all information', { exact: false }).first().click();
  const titleEditor = page.locator('#editor-review-field-title');
  await titleEditor.locator('summary').first().click();
  await titleEditor.locator('[name="value"]').fill('A careful working title');
  await expect(page.getByText('Draft saved locally', { exact: false })).toBeVisible();
  await page.reload();
  await expect(page.locator('main')).toContainText('A careful working title');
  expect((await (await request.get('/__testing/state')).json()).curation_count).toBe(
    initial.curation_count,
  );
});
