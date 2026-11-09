import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Button,
  ComboBox,
  Input,
  Label,
  ListBox,
  ListBoxItem,
  Popover,
  Text,
} from 'react-aria-components';
import { apiGet } from '../api';

interface Option {
  value: string;
  label: string;
  detail: string;
}
interface Options {
  options: Option[];
  total: number;
  more: boolean;
}
export function appendSuggestion(original: string, value: string, maximum = 6000): string {
  const name = value.trim();
  if (!name) return original;
  const next = original + (original && !original.endsWith('\n') ? '\n' : '') + name;
  if (maximum >= 0 && next.length > maximum)
    throw new Error('This field is full. Shorten the list before adding another suggestion.');
  return next;
}
export interface SuggestionInputProps {
  id: string;
  name: string;
  kind: string;
  label?: string;
  value?: string;
  defaultValue?: string;
  onChange?: (value: string) => void;
  maxLength?: number;
  required?: boolean;
  exclude?: string;
  description?: string;
  placeholder?: string;
}

/** Suggestions are local metadata, not a search execution or a verification. */
export function SuggestionInput({
  id,
  name,
  kind,
  label,
  value,
  defaultValue = '',
  onChange,
  maxLength = 200,
  required,
  exclude = '',
  description,
  placeholder,
}: SuggestionInputProps) {
  const [submitted, setSubmitted] = useState(value ?? defaultValue);
  const [input, setInput] = useState(value ?? defaultValue);
  const [filter, setFilter] = useState(input);
  const [opened, setOpened] = useState(false);
  const [focused, setFocused] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const selected = useRef<Option | null>(null);
  const hidden = useRef<HTMLInputElement>(null);
  const options = useQuery({
    queryKey: ['options', kind, filter, exclude],
    queryFn: ({ signal }) =>
      apiGet<Options>(
        '/api/form-options?' + new URLSearchParams({ kind, q: filter, exclude }),
        signal,
      ),
    enabled: opened || focused || (kind === 'books' && !!input),
  });
  useEffect(() => {
    const timer = setTimeout(() => setFilter(input.slice(0, 300)), 160);
    return () => clearTimeout(timer);
  }, [input]);
  useEffect(() => {
    if (value !== undefined && value !== submitted) {
      selected.current = null;
      setSelectedKey(null);
      setSubmitted(value);
      setInput(value);
    }
  }, [value, submitted]);
  useEffect(() => {
    if (kind !== 'books' || selected.current) return;
    const match = options.data?.options.find((item) => item.value === submitted);
    if (match) {
      selected.current = match;
      setSelectedKey(match.value);
      setInput(match.label);
    }
  }, [kind, options.data, submitted]);
  function commit(next: string) {
    setSubmitted(next);
    onChange?.(next);
    // Native form autosave listeners must also see changes from this composite control.
    if (hidden.current) {
      hidden.current.value = next;
      hidden.current.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }
  const choices = [...(options.data?.options ?? [])];
  if (selected.current && !choices.some((o) => o.value === selected.current?.value))
    choices.unshift(selected.current);
  return (
    <div className="suggestion-field">
      <input ref={hidden} type="hidden" name={name} value={submitted} />
      <ComboBox
        allowsCustomValue
        allowsEmptyCollection
        inputValue={input}
        selectedKey={selectedKey}
        items={choices}
        isRequired={required}
        onOpenChange={setOpened}
        onFocusChange={setFocused}
        aria-label={label ? undefined : name.replaceAll('_', ' ')}
        onInputChange={(next) => {
          setInput(next);
          if (next !== selected.current?.label) {
            selected.current = null;
            setSelectedKey(null);
            commit(next);
          }
        }}
        onSelectionChange={(key) => {
          const match = choices.find((o) => o.value === key);
          if (match) {
            selected.current = match;
            setSelectedKey(match.value);
            setInput(match.label);
            commit(match.value);
          }
        }}
      >
        {label && <Label htmlFor={id}>{label}</Label>}
        <div className="combobox-control">
          <Input id={id} maxLength={maxLength} placeholder={placeholder} />
          <Button className="combobox-toggle" aria-label={`Show suggestions for ${label ?? name}`}>
            ▾
          </Button>
        </div>
        {description && (
          <Text slot="description" className="hint">
            {description}
          </Text>
        )}
        <Popover className="combobox-popover">
          <ListBox<Option>
            className="combobox-options"
            renderEmptyState={() =>
              options.isFetching
                ? 'Looking up suggestions…'
                : 'No suggestions. You can enter your own value.'
            }
          >
            {(item) => (
              <ListBoxItem id={item.value} textValue={item.label} className="combobox-option">
                <Text slot="label">{item.label}</Text>
                {item.detail && <Text slot="description">{item.detail}</Text>}
              </ListBoxItem>
            )}
          </ListBox>
          {options.data?.more && <p className="hint">Type more to narrow the suggestions.</p>}
        </Popover>
      </ComboBox>
    </div>
  );
}
