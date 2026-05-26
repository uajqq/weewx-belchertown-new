#set $hour_short = "h"
#set $minute_short = "m"
#set $second_short = "s"
#set $more_than_yesterday_label = "more than yesterday"
#set $less_than_yesterday_label = "less than yesterday"
#try
  #if $obs.label.hour_short != "hour_short"
    #set $hour_short = $obs.label.hour_short
  #end if
#except
  #set $unused_hour_short = None
#end try
#try
  #if $obs.label.minute_short != "minute_short"
    #set $minute_short = $obs.label.minute_short
  #end if
#except
  #set $unused_minute_short = None
#end try
#try
  #if $obs.label.second_short != "second_short"
    #set $second_short = $obs.label.second_short
  #end if
#except
  #set $unused_second_short = None
#end try
#try
  #if $obs.label.more_than_yesterday != "more_than_yesterday"
    #set $more_than_yesterday_label = $obs.label.more_than_yesterday
  #end if
#except
  #set $unused_more_label = None
#end try
#try
  #if $obs.label.less_than_yesterday != "less_than_yesterday"
    #set $less_than_yesterday_label = $obs.label.less_than_yesterday
  #end if
#except
  #set $unused_less_label = None
#end try
#set $sun_altitude_raw = None
#try
  #set $sun_altitude_raw = $almanac.sun.alt
#except
  #set $sun_altitude_raw = None
#end try
#if $sun_altitude_raw is None
  #set $sun_altitude_raw = -90.0
#end if
#if $sun_altitude_raw < 0
  #set $sun_None="<i>(%s)</i>" % $obs.label.sun_always_down
  #set $daylight_str = "0%s 0%s 0%s" % ($hour_short, $minute_short, $second_short)
#else
  #set $sun_None="<i>(%s)</i>" % $obs.label.sun_always_up
  #set $daylight_str = "24%s 0%s 0%s" % ($hour_short, $minute_short, $second_short)
#end if
#set $sunrise_ts = None
#set $sunset_ts = None
#try
  #set $sunrise_ts = $almanac.sun.rise.raw
#except
  #set $sunrise_ts = None
#end try
#try
  #set $sunset_ts = $almanac.sun.set.raw
#except
  #set $sunset_ts = None
#end try
#if $sunrise_ts is None
  #try
    #set $sunrise_ts = $almanac.sunrise.raw
  #except
    #set $sunrise_ts = None
  #end try
#end if
#if $sunset_ts is None
  #try
    #set $sunset_ts = $almanac.sunset.raw
  #except
    #set $sunset_ts = None
  #end try
#end if
#if $sunrise_ts is not None and $sunset_ts is not None
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
  #set $yesterday_sunrise_ts = None
  #set $yesterday_sunset_ts = None
  #try
    #set $yesterday_sunrise_ts = $almanac($almanac_time=$yesterday).sun.rise.raw
  #except
    #set $yesterday_sunrise_ts = None
  #end try
  #if $yesterday_sunrise_ts is None
    #try
      #set $yesterday_sunrise_ts = $almanac($almanac_time=$yesterday).sunrise.raw
    #except
      #set $yesterday_sunrise_ts = None
    #end try
  #end if
  #try
    #set $yesterday_sunset_ts = $almanac($almanac_time=$yesterday).sun.set.raw
  #except
    #set $yesterday_sunset_ts = None
  #end try
  #if $yesterday_sunset_ts is None
    #try
      #set $yesterday_sunset_ts = $almanac($almanac_time=$yesterday).sunset.raw
    #except
      #set $yesterday_sunset_ts = None
    #end try
  #end if
  #if $yesterday_sunrise_ts is not None and $yesterday_sunset_ts is not None
    #set $yesterday_daylight = $yesterday_sunset_ts - $yesterday_sunrise_ts
    #set $difference = $today_daylight - $yesterday_daylight
    #if $difference
      #set $delta = abs($difference)
      #set $amt_minutes = (int($delta) % 3600) // 60
      #set $amt_seconds = int($delta) % 60
      #set $amt_str = "%d%s %d%s" % ($amt_minutes, $minute_short, $amt_seconds, $second_short)
      #if $difference > 0
        #set $delta_str = "%s %s" % ( $amt_str, $more_than_yesterday_label )
      #else
        #set $delta_str = "%s %s" % ( $amt_str, $less_than_yesterday_label )
      #end if
      #set $daylight_str = "%s<br/>%s" % ($daylight_str, $delta_str)
    #end if
  #end if
#end if
