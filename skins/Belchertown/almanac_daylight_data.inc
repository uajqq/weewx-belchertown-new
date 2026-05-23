#set $hour_short = $obs.label.hour_short if $obs.label.hour_short != "hour_short" else "h"
#set $minute_short = $obs.label.minute_short if $obs.label.minute_short != "minute_short" else "m"
#set $second_short = $obs.label.second_short if $obs.label.second_short != "second_short" else "s"
#if $sun_altitude < 0
  #set $sun_None="<i>(%s)</i>" % $obs.label.sun_always_down
  #set $daylight_str = "0%s 0%s 0%s" % ($hour_short, $minute_short, $second_short)
#else
  #set $sun_None="<i>(%s)</i>" % $obs.label.sun_always_up
  #set $daylight_str = "24%s 0%s 0%s" % ($hour_short, $minute_short, $second_short)
#end if
#set $sunrise_ts = $almanac.sun.rise.raw
#set $sunset_ts = $almanac.sun.set.raw
#if $sunrise_ts and $sunset_ts
  #set $now = $current.dateTime.raw
  #set $today_daylight = $sunset_ts -  $sunrise_ts
  #set $seconds = $today_daylight
  #set $hours = $seconds // 3600
  #set $seconds %= 3600
  #set $minutes = $seconds // 60
  #set $seconds %= 60
  #if $hours > 0
    #set $daylight_str = "%d%s %d%s %d%s" % ($hours, $hour_short, $minutes, $minute_short, $seconds, $second_short)
  #else
    #set $daylight_str = "%d%s %d%s" % ($minutes, $minute_short, $seconds, $second_short)
  #end if
  #set $yesterday = $now - 24*3600
  #set $yesterday_daylight = $almanac($almanac_time=$yesterday).sun.set.raw - $almanac($almanac_time=$yesterday).sun.rise.raw
  #set $difference = $today_daylight - $yesterday_daylight
  #if $difference
    #set $delta = abs($difference)
    #set $amt_minutes = (int($delta) % 3600) // 60
    #set $amt_seconds = int($delta) % 60
    #set $amt_str = "%d%s %d%s" % ($amt_minutes, $minute_short, $amt_seconds, $second_short)
    #if $difference > 0
      #set $delta_str = "%s %s" % ( $amt_str, $obs.label.more_than_yesterday )
    #else
      #set $delta_str = "%s %s" % ( $amt_str, $obs.label.less_than_yesterday )
    #end if
    #set $daylight_str = "%s<br/>%s" % ($daylight_str, $delta_str)
  #end if
#end if
